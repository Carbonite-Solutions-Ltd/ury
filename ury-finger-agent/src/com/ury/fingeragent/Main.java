package com.ury.fingeragent;

import java.io.IOException;
import java.util.Map;

/**
 * URY Finger Agent — entry point + HTTP routing.
 *
 * <p>Local HTTP service on each cashier's Windows PC, alongside QZ Tray.
 * Listens on {@code 127.0.0.1:9994} and exposes a clean REST API for
 * the React POS to capture fingerprints. Internally loads
 * {@link com.zkteco.biometric.FingerprintSensorEx} which uses JNI to
 * talk to the ZKFinger native DLLs (zkfinger10.dll, ZKFPCap.dll, …).
 *
 * <p>Why we wrote our own agent instead of using ZKBioOnline: the
 * bundled ZKBioOnline.exe (Oct 2020 build) crashes with
 * STATUS_STACK_BUFFER_OVERRUN when loading newer fingerprint DLLs, and
 * ISSOnline's HTTP REST API only exposes ActiveX-bound commands that
 * don't work in modern browsers. Owning the agent lets us pick the
 * wire format. See {@link MiniHttp} for the reason we don't use
 * {@code com.sun.net.httpserver.HttpServer} (QZ Tray's bundled JRE
 * lacks the {@code jdk.httpserver} module).
 *
 * <p>API surface (all responses are JSON):
 * <pre>
 *   GET  /                  — agent info (name, version, java version)
 *   GET  /status            — device + session state
 *   POST /open              — initialise SDK + open device
 *   POST /close             — close device + free SDK
 *   POST /enroll/start      — start a 3-scan enrollment session
 *   GET  /enroll/poll       — poll for enrollment progress + master template
 *   POST /enroll/cancel     — cancel the current enrollment
 *   POST /capture/start     — start a single-scan capture
 *   GET  /capture/poll      — poll for capture result
 *   POST /capture/cancel    — cancel the current capture
 *   POST /verify            — 1:1 match two base64 templates
 * </pre>
 *
 * <p>CORS: All responses include {@code Access-Control-Allow-Origin: *}
 * because the agent only listens on 127.0.0.1 — there's no security
 * gain from origin restrictions, and the URY Frappe site is on a
 * different origin (cloud-hosted) than the local agent.
 */
public final class Main {

    public static final String AGENT_NAME = "URY Finger Agent";
    public static final String AGENT_VERSION = "1.0.0";
    private static final int DEFAULT_PORT = 9994;
    private static final String LISTEN_ADDR = "127.0.0.1";

    private final FingerCore core = new FingerCore();

    public static void main(String[] args) throws IOException {
        int port = DEFAULT_PORT;
        for (int i = 0; i < args.length; i++) {
            if ("--port".equals(args[i]) && i + 1 < args.length) {
                port = Integer.parseInt(args[++i]);
            }
        }
        new Main().run(port);
    }

    private void run(int port) throws IOException {
        MiniHttp server = new MiniHttp(LISTEN_ADDR, port);
        server.route("/",                  jsonRoute(this::handleRoot));
        server.route("/status",            jsonRoute(this::handleStatus));
        server.route("/open",              jsonRoute(this::handleOpen));
        server.route("/close",             jsonRoute(this::handleClose));
        server.route("/enroll/start",      jsonRoute(this::handleEnrollStart));
        server.route("/enroll/poll",       jsonRoute(this::handleEnrollPoll));
        server.route("/enroll/cancel",     jsonRoute(this::handleEnrollCancel));
        server.route("/capture/start",     jsonRoute(this::handleCaptureStart));
        server.route("/capture/poll",      jsonRoute(this::handleCapturePoll));
        server.route("/capture/cancel",    jsonRoute(this::handleCaptureCancel));
        server.route("/verify",            jsonRoute(this::handleVerify));

        server.start();
        System.out.println("[" + AGENT_NAME + " v" + AGENT_VERSION + "] listening on http://" +
                LISTEN_ADDR + ":" + port);
        System.out.println("Press Ctrl+C to stop.");

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            System.out.println("[shutdown] closing reader...");
            try { core.close(); } catch (Exception ignored) {}
            server.stop();
        }, "ury-finger-shutdown"));

        // Block forever
        try {
            Thread.currentThread().join();
        } catch (InterruptedException ignored) {}
    }

    // ---------------------------------------------------------------
    // Handlers
    // ---------------------------------------------------------------

    private Object handleRoot(MiniHttp.Request req, Map<String, Object> body) {
        return Json.obj(
            "agent", AGENT_NAME,
            "version", AGENT_VERSION,
            "java_version", System.getProperty("java.version"),
            "java_vendor", System.getProperty("java.vendor"),
            "os_arch", System.getProperty("os.arch"),
            "os_name", System.getProperty("os.name"),
            "uptime_ms", System.currentTimeMillis()
        );
    }

    private Object handleStatus(MiniHttp.Request req, Map<String, Object> body) {
        return core.statusMap();
    }

    private Object handleOpen(MiniHttp.Request req, Map<String, Object> body) {
        return core.open();
    }

    private Object handleClose(MiniHttp.Request req, Map<String, Object> body) {
        return core.close();
    }

    private Object handleEnrollStart(MiniHttp.Request req, Map<String, Object> body) {
        return FingerCore.enrollSummary(core.startEnroll());
    }

    private Object handleEnrollPoll(MiniHttp.Request req, Map<String, Object> body) {
        String sessionId = bodyOrQuery(body, req, "session_id");
        return FingerCore.enrollSummary(core.getEnrollState(sessionId));
    }

    private Object handleEnrollCancel(MiniHttp.Request req, Map<String, Object> body) {
        return core.cancelEnroll();
    }

    private Object handleCaptureStart(MiniHttp.Request req, Map<String, Object> body) {
        return FingerCore.captureSummary(core.startCapture());
    }

    private Object handleCapturePoll(MiniHttp.Request req, Map<String, Object> body) {
        return FingerCore.captureSummary(core.getCaptureState());
    }

    private Object handleCaptureCancel(MiniHttp.Request req, Map<String, Object> body) {
        return core.cancelCapture();
    }

    private Object handleVerify(MiniHttp.Request req, Map<String, Object> body) {
        String t1 = bodyString(body, "template1");
        String t2 = bodyString(body, "template2");
        return core.verify(t1, t2);
    }

    // ---------------------------------------------------------------
    // Routing helpers
    // ---------------------------------------------------------------

    @FunctionalInterface
    private interface JsonHandler {
        Object handle(MiniHttp.Request req, Map<String, Object> body) throws Exception;
    }

    private MiniHttp.Handler jsonRoute(JsonHandler h) {
        return req -> {
            MiniHttp.Response resp = new MiniHttp.Response();
            // CORS headers on every response
            resp.header("Access-Control-Allow-Origin", "*");
            resp.header("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
            resp.header("Access-Control-Allow-Headers", "Content-Type, X-Requested-With, X-URY-Agent");
            resp.header("Access-Control-Max-Age", "300");

            if ("OPTIONS".equalsIgnoreCase(req.method)) {
                return resp.status(204);
            }
            try {
                Map<String, Object> reqBody = readBodyJson(req);
                Object result = h.handle(req, reqBody);
                if (result == null) result = Json.obj();
                return resp.status(200).json(Json.stringify(result));
            } catch (FingerCore.AgentException ae) {
                int status = mapAgentError(ae.code);
                return resp.status(status).json(Json.stringify(Json.obj(
                    "error", ae.code, "message", ae.getMessage()
                )));
            } catch (Throwable t) {
                t.printStackTrace();
                return resp.status(500).json(Json.stringify(Json.obj(
                    "error", "internal",
                    "message", t.getClass().getSimpleName() + ": " + t.getMessage()
                )));
            }
        };
    }

    private static int mapAgentError(String code) {
        switch (code) {
            case "bad_request": return 400;
            case "not_open":
            case "busy":
            case "stale_session":
                return 409;
            case "no_session": return 404;
            case "no_device":
            case "init_failed":
            case "open_failed":
            case "dbinit_failed":
                return 503;
            default: return 500;
        }
    }

    private static Map<String, Object> readBodyJson(MiniHttp.Request req) {
        if (!"POST".equalsIgnoreCase(req.method)) return Json.obj();
        if (req.body.length == 0) return Json.obj();
        String text = req.bodyText().trim();
        if (text.isEmpty()) return Json.obj();
        try {
            return Json.parseObject(text);
        } catch (Exception ex) {
            throw new FingerCore.AgentException("bad_request", "Invalid JSON: " + ex.getMessage());
        }
    }

    private static String bodyString(Map<String, Object> body, String key) {
        Object v = body.get(key);
        return v == null ? null : v.toString();
    }

    private static String bodyOrQuery(Map<String, Object> body, MiniHttp.Request req, String key) {
        String v = bodyString(body, key);
        if (v != null) return v;
        return req.query.get(key);
    }
}
