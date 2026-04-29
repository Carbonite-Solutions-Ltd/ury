package com.ury.fingeragent;

import com.zkteco.biometric.FingerprintSensorEx;
import com.zkteco.biometric.FingerprintSensorErrorCode;

import java.util.Base64;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Owns the lifecycle of the ZKFinger SDK — device handle, DB cache,
 * and the background capture thread that polls the reader and routes
 * each scan to either the active enrollment session or the active
 * single-capture promise.
 *
 * <p>Single-instance per process. Thread-safe under simple invariants:
 * <ul>
 *   <li>Only ONE enrollment OR single capture is active at any time.
 *       Callers are blocked from starting a new one until the previous
 *       resolves.</li>
 *   <li>Device open/close are explicit verbs — the agent does not
 *       auto-open on every request because each open()/close() pair
 *       takes ~1 second on the SDK. Enrollment + verify both expect
 *       the device to already be open.</li>
 *   <li>The poller spins at ~100ms between attempts (matches the
 *       upstream Java demo).</li>
 * </ul>
 */
public final class FingerCore {

    public static final int ENROLL_SCANS = 3;
    private static final int TEMPLATE_BUF = 2048;
    private static final long POLL_INTERVAL_MS = 100;
    private static final long INACTIVE_SLEEP_MS = 200;

    public enum SessionKind { IDLE, ENROLL, CAPTURE }

    private long mhDevice = 0;
    private long mhDB = 0;
    private int fpWidth = 0;
    private int fpHeight = 0;
    private byte[] imgBuf = new byte[0];
    private volatile boolean stopFlag = true;

    private Thread workerThread;

    // Session state. Only ONE of enroll/capture is active at any time.
    // Reads are non-blocking; writes are synchronised via stateLock.
    private final Object stateLock = new Object();
    private SessionKind sessionKind = SessionKind.IDLE;

    // Enrollment session ----------------------------------------------------
    private final byte[][] enrollScans = new byte[ENROLL_SCANS][TEMPLATE_BUF];
    private int enrollIdx = 0;
    private volatile EnrollState enrollState;

    public static final class EnrollState {
        public final String sessionId;
        public volatile int scansCaptured;
        public volatile boolean done;
        public volatile boolean cancelled;
        public volatile String errorMessage;
        public volatile String masterTemplateBase64;
        public volatile int masterTemplateLength;
        public volatile long startedAt;
        public volatile long updatedAt;

        EnrollState(String sessionId) {
            this.sessionId = sessionId;
            this.scansCaptured = 0;
            this.done = false;
            this.cancelled = false;
            this.startedAt = System.currentTimeMillis();
            this.updatedAt = startedAt;
        }
    }

    // Single capture session ------------------------------------------------
    private final AtomicReference<CaptureState> captureState = new AtomicReference<>(null);

    public static final class CaptureState {
        public volatile boolean done;
        public volatile boolean cancelled;
        public volatile String errorMessage;
        public volatile String templateBase64;
        public volatile int templateLength;
        public volatile long startedAt;
        public volatile long updatedAt;

        CaptureState() {
            this.startedAt = System.currentTimeMillis();
            this.updatedAt = startedAt;
        }
    }

    // ---------------------------------------------------------------
    // Lifecycle
    // ---------------------------------------------------------------

    /**
     * Initialise the SDK, open the first device, and start the capture
     * worker. Returns a status map describing the open device.
     *
     * @throws AgentException if Init fails, no device present, or open
     *     fails. The caller MUST surface these errors to the user — they
     *     mean the reader isn't usable yet.
     */
    public synchronized Map<String, Object> open() {
        if (mhDevice != 0) {
            return statusMap();
        }
        int ret = FingerprintSensorEx.Init();
        if (ret != FingerprintSensorErrorCode.ZKFP_ERR_OK) {
            throw new AgentException("init_failed", "FingerprintSensorEx.Init failed (ret=" + ret + ")");
        }
        int count = FingerprintSensorEx.GetDeviceCount();
        if (count <= 0) {
            FingerprintSensorEx.Terminate();
            throw new AgentException("no_device", "No fingerprint reader connected (GetDeviceCount=" + count + "). " +
                    "Plug a ZK reader into a USB port and try again.");
        }
        long handle = FingerprintSensorEx.OpenDevice(0);
        if (handle == 0) {
            FingerprintSensorEx.Terminate();
            throw new AgentException("open_failed", "FingerprintSensorEx.OpenDevice(0) returned 0 — driver could not " +
                    "attach to the device. Try unplugging and replugging the reader.");
        }
        mhDevice = handle;
        mhDB = FingerprintSensorEx.DBInit();
        if (mhDB == 0) {
            FingerprintSensorEx.CloseDevice(mhDevice);
            mhDevice = 0;
            FingerprintSensorEx.Terminate();
            throw new AgentException("dbinit_failed", "FingerprintSensorEx.DBInit returned 0 — could not initialise " +
                    "the matching DB cache.");
        }
        // Use the SDK's native template format (the most efficient one;
        // ANSI/ISO are slower and are mostly for export/interop).
        FingerprintSensorEx.DBSetParameter(mhDB, 5010, 0);

        byte[] paramValue = new byte[4];
        int[] size = new int[]{4};
        FingerprintSensorEx.GetParameters(mhDevice, 1, paramValue, size);
        fpWidth = byteArrayToInt(paramValue);
        size[0] = 4;
        FingerprintSensorEx.GetParameters(mhDevice, 2, paramValue, size);
        fpHeight = byteArrayToInt(paramValue);
        if (fpWidth <= 0 || fpHeight <= 0) {
            // Some readers report 0 if Init is racing — retry once
            fpWidth = Math.max(fpWidth, 256);
            fpHeight = Math.max(fpHeight, 360);
        }
        imgBuf = new byte[fpWidth * fpHeight];
        stopFlag = false;
        workerThread = new Thread(this::pollLoop, "ury-finger-poll");
        workerThread.setDaemon(true);
        workerThread.start();
        return statusMap();
    }

    public synchronized Map<String, Object> close() {
        stopFlag = true;
        Thread t = workerThread;
        workerThread = null;
        if (t != null) {
            try { t.join(2000); } catch (InterruptedException ignored) {}
        }
        synchronized (stateLock) {
            sessionKind = SessionKind.IDLE;
            enrollState = null;
            captureState.set(null);
            enrollIdx = 0;
        }
        if (mhDB != 0) {
            FingerprintSensorEx.DBFree(mhDB);
            mhDB = 0;
        }
        if (mhDevice != 0) {
            FingerprintSensorEx.CloseDevice(mhDevice);
            mhDevice = 0;
        }
        FingerprintSensorEx.Terminate();
        Map<String, Object> m = Json.obj();
        m.put("opened", false);
        return m;
    }

    public Map<String, Object> statusMap() {
        Map<String, Object> m = Json.obj();
        m.put("opened", mhDevice != 0);
        m.put("device_handle", mhDevice);
        m.put("db_handle", mhDB);
        m.put("fp_width", fpWidth);
        m.put("fp_height", fpHeight);
        m.put("session", sessionKind.name());
        if (enrollState != null) {
            m.put("enroll", enrollSummary(enrollState));
        }
        if (captureState.get() != null) {
            m.put("capture", captureSummary(captureState.get()));
        }
        return m;
    }

    // ---------------------------------------------------------------
    // Enrollment
    // ---------------------------------------------------------------

    public EnrollState startEnroll() {
        if (mhDevice == 0) throw new AgentException("not_open", "Reader is not open. Call /open first.");
        synchronized (stateLock) {
            if (sessionKind != SessionKind.IDLE) {
                throw new AgentException("busy", "Another " + sessionKind + " session is already running. " +
                        "Cancel it before starting a new enrollment.");
            }
            enrollIdx = 0;
            EnrollState st = new EnrollState(java.util.UUID.randomUUID().toString());
            enrollState = st;
            sessionKind = SessionKind.ENROLL;
            return st;
        }
    }

    public EnrollState getEnrollState(String sessionId) {
        EnrollState st = enrollState;
        if (st == null) {
            throw new AgentException("no_session", "No active enrollment session.");
        }
        if (sessionId != null && !sessionId.equals(st.sessionId)) {
            throw new AgentException("stale_session", "Enrollment session id mismatch — start a new enrollment.");
        }
        return st;
    }

    public Map<String, Object> cancelEnroll() {
        synchronized (stateLock) {
            if (sessionKind == SessionKind.ENROLL && enrollState != null) {
                enrollState.cancelled = true;
                enrollState.done = true;
                enrollState.errorMessage = "cancelled";
                sessionKind = SessionKind.IDLE;
            }
            return Json.obj("cancelled", true);
        }
    }

    public static Map<String, Object> enrollSummary(EnrollState st) {
        Map<String, Object> m = Json.obj();
        m.put("session_id", st.sessionId);
        m.put("scans_captured", st.scansCaptured);
        m.put("scans_required", ENROLL_SCANS);
        m.put("done", st.done);
        m.put("cancelled", st.cancelled);
        if (st.errorMessage != null) m.put("error", st.errorMessage);
        if (st.masterTemplateBase64 != null) {
            m.put("template_base64", st.masterTemplateBase64);
            m.put("template_length", st.masterTemplateLength);
        }
        m.put("started_at", st.startedAt);
        m.put("updated_at", st.updatedAt);
        return m;
    }

    // ---------------------------------------------------------------
    // Single capture (used by verify flow)
    // ---------------------------------------------------------------

    public CaptureState startCapture() {
        if (mhDevice == 0) throw new AgentException("not_open", "Reader is not open. Call /open first.");
        synchronized (stateLock) {
            if (sessionKind != SessionKind.IDLE) {
                throw new AgentException("busy", "Another " + sessionKind + " session is already running.");
            }
            CaptureState st = new CaptureState();
            captureState.set(st);
            sessionKind = SessionKind.CAPTURE;
            return st;
        }
    }

    public CaptureState getCaptureState() {
        CaptureState st = captureState.get();
        if (st == null) throw new AgentException("no_session", "No active capture session.");
        return st;
    }

    public Map<String, Object> cancelCapture() {
        synchronized (stateLock) {
            CaptureState st = captureState.get();
            if (st != null) {
                st.cancelled = true;
                st.done = true;
                st.errorMessage = "cancelled";
                sessionKind = SessionKind.IDLE;
            }
            return Json.obj("cancelled", true);
        }
    }

    public static Map<String, Object> captureSummary(CaptureState st) {
        Map<String, Object> m = Json.obj();
        m.put("done", st.done);
        m.put("cancelled", st.cancelled);
        if (st.errorMessage != null) m.put("error", st.errorMessage);
        if (st.templateBase64 != null) {
            m.put("template_base64", st.templateBase64);
            m.put("template_length", st.templateLength);
        }
        m.put("started_at", st.startedAt);
        m.put("updated_at", st.updatedAt);
        return m;
    }

    // ---------------------------------------------------------------
    // 1:1 match
    // ---------------------------------------------------------------

    public Map<String, Object> verify(String t1Base64, String t2Base64) {
        if (mhDB == 0) throw new AgentException("not_open", "Reader is not open. Call /open first.");
        byte[] t1 = decodeTemplate(t1Base64, "template1");
        byte[] t2 = decodeTemplate(t2Base64, "template2");
        int score = FingerprintSensorEx.DBMatch(mhDB, t1, t2);
        Map<String, Object> m = Json.obj();
        m.put("score", score);
        m.put("matched", score > 0);
        return m;
    }

    private static byte[] decodeTemplate(String base64, String fieldName) {
        if (base64 == null || base64.isEmpty()) {
            throw new AgentException("bad_request", fieldName + " is required");
        }
        try {
            return Base64.getDecoder().decode(base64.trim());
        } catch (IllegalArgumentException ex) {
            throw new AgentException("bad_request", fieldName + " is not valid base64");
        }
    }

    // ---------------------------------------------------------------
    // Background poller
    // ---------------------------------------------------------------

    private void pollLoop() {
        byte[] tmpTemplate = new byte[TEMPLATE_BUF];
        int[] tmpLen = new int[1];
        while (!stopFlag) {
            SessionKind kind;
            synchronized (stateLock) { kind = sessionKind; }
            if (kind == SessionKind.IDLE) {
                sleep(INACTIVE_SLEEP_MS);
                continue;
            }
            tmpLen[0] = TEMPLATE_BUF;
            int ret = FingerprintSensorEx.AcquireFingerprint(mhDevice, imgBuf, tmpTemplate, tmpLen);
            if (ret == FingerprintSensorErrorCode.ZKFP_ERR_OK) {
                if (kind == SessionKind.ENROLL) {
                    handleEnrollScan(tmpTemplate, tmpLen[0]);
                } else if (kind == SessionKind.CAPTURE) {
                    handleSingleCapture(tmpTemplate, tmpLen[0]);
                }
            }
            sleep(POLL_INTERVAL_MS);
        }
    }

    private void handleEnrollScan(byte[] tmpTemplate, int tmpLen) {
        EnrollState st = enrollState;
        if (st == null || st.cancelled || st.done) return;
        // Reject if the user pressed a different finger compared to scan 1
        if (enrollIdx > 0) {
            int matchScore = FingerprintSensorEx.DBMatch(mhDB, enrollScans[enrollIdx - 1], tmpTemplate);
            if (matchScore <= 0) {
                // Different finger — restart enrollment
                st.errorMessage = "Different finger detected. Please use the same finger for all 3 scans.";
                st.scansCaptured = 0;
                enrollIdx = 0;
                st.updatedAt = System.currentTimeMillis();
                return;
            }
        }
        st.errorMessage = null;
        System.arraycopy(tmpTemplate, 0, enrollScans[enrollIdx], 0, TEMPLATE_BUF);
        enrollIdx++;
        st.scansCaptured = enrollIdx;
        st.updatedAt = System.currentTimeMillis();

        if (enrollIdx == ENROLL_SCANS) {
            int[] retLen = new int[]{TEMPLATE_BUF};
            byte[] regTemp = new byte[TEMPLATE_BUF];
            int rc = FingerprintSensorEx.DBMerge(mhDB, enrollScans[0], enrollScans[1], enrollScans[2], regTemp, retLen);
            if (rc != FingerprintSensorErrorCode.ZKFP_ERR_OK) {
                st.errorMessage = "DBMerge failed (rc=" + rc + "). Please re-enrol.";
                st.scansCaptured = 0;
                enrollIdx = 0;
                return;
            }
            byte[] trimmed = new byte[retLen[0]];
            System.arraycopy(regTemp, 0, trimmed, 0, retLen[0]);
            st.masterTemplateBase64 = Base64.getEncoder().encodeToString(trimmed);
            st.masterTemplateLength = retLen[0];
            st.done = true;
            st.updatedAt = System.currentTimeMillis();
            synchronized (stateLock) { sessionKind = SessionKind.IDLE; }
        }
    }

    private void handleSingleCapture(byte[] tmpTemplate, int tmpLen) {
        CaptureState st = captureState.get();
        if (st == null || st.cancelled || st.done) return;
        byte[] trimmed = new byte[tmpLen];
        System.arraycopy(tmpTemplate, 0, trimmed, 0, tmpLen);
        st.templateBase64 = Base64.getEncoder().encodeToString(trimmed);
        st.templateLength = tmpLen;
        st.done = true;
        st.updatedAt = System.currentTimeMillis();
        synchronized (stateLock) { sessionKind = SessionKind.IDLE; }
    }

    private static void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException ignored) {}
    }

    private static int byteArrayToInt(byte[] bytes) {
        return ((bytes[3] & 0xff) << 24) |
               ((bytes[2] & 0xff) << 16) |
               ((bytes[1] & 0xff) <<  8) |
                (bytes[0] & 0xff);
    }

    // ---------------------------------------------------------------
    // Custom unchecked exception
    // ---------------------------------------------------------------

    public static final class AgentException extends RuntimeException {
        public final String code;
        public AgentException(String code, String message) {
            super(message);
            this.code = code;
        }
    }
}
