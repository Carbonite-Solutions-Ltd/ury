package com.ury.fingeragent;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Minimal HTTP/1.1 server using only {@code java.base}.
 *
 * <p>QZ Tray ships a stripped-down JRE that excludes the
 * {@code jdk.httpserver} module, so the standard
 * {@code com.sun.net.httpserver.HttpServer} isn't available on the
 * machines we target. This class is the workaround: about 200 lines of
 * vanilla socket code that handles GET / POST / OPTIONS, request body
 * up to a sane limit, JSON content-type, and CORS — everything the
 * agent's REST surface needs and nothing more.
 *
 * <p>NOT a general-purpose HTTP server. Limitations are deliberate:
 * <ul>
 *   <li>HTTP/1.1 with {@code Connection: close} only — no keep-alive.</li>
 *   <li>No chunked request bodies (Content-Length required).</li>
 *   <li>4 KB request line limit, 16 KB header limit, 1 MB body limit.</li>
 *   <li>One thread per request from a fixed-size pool.</li>
 * </ul>
 */
public final class MiniHttp {

    private static final int MAX_REQUEST_LINE = 4 * 1024;
    private static final int MAX_HEADER_BLOCK = 16 * 1024;
    private static final int MAX_BODY = 1024 * 1024;
    private static final int IDLE_TIMEOUT_MS = 30_000;

    @FunctionalInterface
    public interface Handler {
        Response handle(Request req) throws Exception;
    }

    public static final class Request {
        public final String method;
        public final String path;
        public final Map<String, String> query;
        public final Map<String, String> headers;
        public final byte[] body;
        public final String remoteIp;

        Request(String method, String path, Map<String, String> query,
                Map<String, String> headers, byte[] body, String remoteIp) {
            this.method = method;
            this.path = path;
            this.query = query == null ? Collections.emptyMap() : query;
            this.headers = headers == null ? Collections.emptyMap() : headers;
            this.body = body == null ? new byte[0] : body;
            this.remoteIp = remoteIp;
        }

        public String bodyText() {
            return new String(body, StandardCharsets.UTF_8);
        }
    }

    public static final class Response {
        public int status = 200;
        public final Map<String, String> headers = new LinkedHashMap<>();
        public byte[] body = new byte[0];

        public Response status(int s) { this.status = s; return this; }
        public Response header(String k, String v) { this.headers.put(k, v); return this; }
        public Response body(String s) { this.body = s.getBytes(StandardCharsets.UTF_8); return this; }
        public Response json(String s) {
            this.headers.put("Content-Type", "application/json; charset=utf-8");
            return body(s);
        }
    }

    private final InetAddress bindAddr;
    private final int port;
    private ServerSocket serverSocket;
    private ExecutorService pool;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final Map<String, Handler> routes = new LinkedHashMap<>();

    public MiniHttp(String bindHost, int port) throws IOException {
        this.bindAddr = InetAddress.getByName(bindHost);
        this.port = port;
    }

    public MiniHttp route(String path, Handler h) {
        routes.put(path, h);
        return this;
    }

    public void start() throws IOException {
        if (!running.compareAndSet(false, true)) return;
        serverSocket = new ServerSocket(port, 32, bindAddr);
        pool = Executors.newFixedThreadPool(8, r -> {
            Thread t = new Thread(r, "ury-finger-http");
            t.setDaemon(true);
            return t;
        });
        Thread acceptor = new Thread(this::acceptLoop, "ury-finger-acceptor");
        acceptor.setDaemon(true);
        acceptor.start();
    }

    public void stop() {
        running.set(false);
        try { if (serverSocket != null) serverSocket.close(); } catch (Exception ignored) {}
        if (pool != null) pool.shutdownNow();
    }

    public int getPort() { return port; }

    private void acceptLoop() {
        while (running.get()) {
            Socket s;
            try {
                s = serverSocket.accept();
            } catch (IOException e) {
                if (running.get()) e.printStackTrace();
                break;
            }
            try {
                s.setSoTimeout(IDLE_TIMEOUT_MS);
            } catch (Exception ignored) {}
            pool.submit(() -> handleSocket(s));
        }
    }

    private void handleSocket(Socket s) {
        try (Socket sock = s) {
            InputStream in = sock.getInputStream();
            OutputStream out = sock.getOutputStream();

            Request req = readRequest(in, sock.getInetAddress().getHostAddress());
            if (req == null) return;

            Response resp;
            try {
                Handler h = routes.get(req.path);
                if (h == null) {
                    // Match longest-prefix as fallback (e.g. for nested routes)
                    h = routes.getOrDefault("*", req2 -> notFound());
                }
                resp = h.handle(req);
                if (resp == null) resp = notFound();
            } catch (Throwable t) {
                t.printStackTrace();
                resp = new Response()
                    .status(500)
                    .json("{\"error\":\"internal\",\"message\":\"" + escape(t.getClass().getSimpleName() + ": " + t.getMessage()) + "\"}");
            }
            writeResponse(out, resp);
        } catch (Exception e) {
            // socket level failure - just drop
        }
    }

    private Request readRequest(InputStream in, String remoteIp) throws IOException {
        // Buffered reader is awkward for binary bodies, so we read header
        // bytes ourselves up to "\r\n\r\n", then the body as raw bytes.
        byte[] hdrBuf = new byte[MAX_HEADER_BLOCK];
        int hdrLen = 0;
        int sepIdx = -1;
        while (hdrLen < hdrBuf.length) {
            int b = in.read();
            if (b < 0) return null;
            hdrBuf[hdrLen++] = (byte) b;
            if (hdrLen >= 4
                && hdrBuf[hdrLen - 4] == '\r' && hdrBuf[hdrLen - 3] == '\n'
                && hdrBuf[hdrLen - 2] == '\r' && hdrBuf[hdrLen - 1] == '\n') {
                sepIdx = hdrLen - 4;
                break;
            }
        }
        if (sepIdx < 0) return null;
        String headerBlock = new String(hdrBuf, 0, sepIdx, StandardCharsets.ISO_8859_1);
        String[] lines = headerBlock.split("\r\n");
        if (lines.length == 0) return null;

        String[] requestLine = lines[0].split(" ", 3);
        if (requestLine.length < 3) return null;
        if (requestLine[0].length() > 16 || lines[0].length() > MAX_REQUEST_LINE) return null;

        String method = requestLine[0];
        String fullPath = requestLine[1];
        String path = fullPath;
        Map<String, String> query = Collections.emptyMap();
        int qIdx = fullPath.indexOf('?');
        if (qIdx >= 0) {
            path = fullPath.substring(0, qIdx);
            query = parseQuery(fullPath.substring(qIdx + 1));
        }

        Map<String, String> headers = new LinkedHashMap<>();
        for (int i = 1; i < lines.length; i++) {
            int colon = lines[i].indexOf(':');
            if (colon > 0) {
                String name = lines[i].substring(0, colon).trim().toLowerCase();
                String value = lines[i].substring(colon + 1).trim();
                headers.put(name, value);
            }
        }

        byte[] body = new byte[0];
        String cl = headers.get("content-length");
        if (cl != null) {
            int len = Integer.parseInt(cl);
            if (len > MAX_BODY) {
                throw new IOException("body too large (" + len + ")");
            }
            if (len > 0) {
                body = new byte[len];
                int read = 0;
                while (read < len) {
                    int n = in.read(body, read, len - read);
                    if (n < 0) break;
                    read += n;
                }
                if (read < len) {
                    throw new IOException("short body: got " + read + ", expected " + len);
                }
            }
        }

        return new Request(method, path, query, headers, body, remoteIp);
    }

    private static Map<String, String> parseQuery(String q) {
        Map<String, String> m = new LinkedHashMap<>();
        for (String pair : q.split("&")) {
            if (pair.isEmpty()) continue;
            int eq = pair.indexOf('=');
            String k = eq < 0 ? pair : pair.substring(0, eq);
            String v = eq < 0 ? "" : pair.substring(eq + 1);
            try {
                m.put(URLDecoder.decode(k, "UTF-8"), URLDecoder.decode(v, "UTF-8"));
            } catch (Exception ex) {
                m.put(k, v);
            }
        }
        return m;
    }

    private static void writeResponse(OutputStream out, Response r) throws IOException {
        StringBuilder sb = new StringBuilder(256);
        sb.append("HTTP/1.1 ").append(r.status).append(' ').append(reasonFor(r.status)).append("\r\n");
        // Defaults
        if (!r.headers.containsKey("Content-Type")) {
            r.headers.put("Content-Type", "text/plain; charset=utf-8");
        }
        r.headers.put("Content-Length", String.valueOf(r.body.length));
        r.headers.put("Connection", "close");
        for (Map.Entry<String, String> e : r.headers.entrySet()) {
            sb.append(e.getKey()).append(": ").append(e.getValue()).append("\r\n");
        }
        sb.append("\r\n");
        out.write(sb.toString().getBytes(StandardCharsets.ISO_8859_1));
        out.write(r.body);
        out.flush();
    }

    private static String reasonFor(int status) {
        switch (status) {
            case 200: return "OK";
            case 204: return "No Content";
            case 400: return "Bad Request";
            case 404: return "Not Found";
            case 405: return "Method Not Allowed";
            case 409: return "Conflict";
            case 500: return "Internal Server Error";
            case 503: return "Service Unavailable";
            default:  return "Status " + status;
        }
    }

    private static Response notFound() {
        return new Response().status(404).json("{\"error\":\"not_found\",\"message\":\"No handler for this path.\"}");
    }

    private static String escape(String s) {
        if (s == null) return "";
        StringBuilder b = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
            else b.append(c);
        }
        return b.toString();
    }
}
