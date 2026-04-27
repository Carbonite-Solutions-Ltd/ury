package com.ury.fingeragent;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal JSON encoder/decoder for the agent's wire format.
 *
 * <p>We deliberately avoid Jackson/Gson here so the agent ships as a
 * single 50-ish KB jar with zero external dependencies. The wire is
 * simple — flat objects, strings, numbers, booleans, arrays of those.
 * If we ever need richer schemas, swap this for a real library.
 *
 * <p>Encoder: {@link #stringify(Object)} accepts {@link Map},
 * {@link List}, {@link String}, {@link Number}, {@link Boolean}, and
 * {@code null}, and emits compliant JSON.
 *
 * <p>Decoder: {@link #parse(String)} returns {@link Map}, {@link List},
 * {@link String}, {@link Long}, {@link Double}, {@link Boolean}, or
 * {@code null}.
 */
public final class Json {

    private Json() {}

    // ---------------------------------------------------------------
    // Encode
    // ---------------------------------------------------------------

    public static String stringify(Object value) {
        StringBuilder sb = new StringBuilder();
        write(sb, value);
        return sb.toString();
    }

    private static void write(StringBuilder sb, Object v) {
        if (v == null) {
            sb.append("null");
        } else if (v instanceof Boolean) {
            sb.append(((Boolean) v) ? "true" : "false");
        } else if (v instanceof Number) {
            // Avoid scientific notation that breaks JS clients
            String s = v.toString();
            sb.append(s);
        } else if (v instanceof String) {
            writeString(sb, (String) v);
        } else if (v instanceof Map<?, ?>) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                if (!first) sb.append(',');
                first = false;
                writeString(sb, String.valueOf(e.getKey()));
                sb.append(':');
                write(sb, e.getValue());
            }
            sb.append('}');
        } else if (v instanceof List<?>) {
            sb.append('[');
            boolean first = true;
            for (Object item : (List<?>) v) {
                if (!first) sb.append(',');
                first = false;
                write(sb, item);
            }
            sb.append(']');
        } else if (v instanceof byte[]) {
            // Base64 encode raw bytes. Callers usually convert to base64
            // before adding to the map, but this is a safety net.
            writeString(sb, java.util.Base64.getEncoder().encodeToString((byte[]) v));
        } else {
            writeString(sb, v.toString());
        }
    }

    private static void writeString(StringBuilder sb, String s) {
        sb.append('"');
        int len = s.length();
        for (int i = 0; i < len; i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\': sb.append("\\\\"); break;
                case '"':  sb.append("\\\""); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        sb.append('"');
    }

    // ---------------------------------------------------------------
    // Decode
    // ---------------------------------------------------------------

    public static Object parse(String text) {
        if (text == null) return null;
        Parser p = new Parser(text);
        Object value = p.parseValue();
        p.skipWs();
        if (p.pos < p.src.length()) {
            throw new IllegalArgumentException("Unexpected trailing characters at " + p.pos);
        }
        return value;
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> parseObject(String text) {
        Object v = parse(text);
        if (v instanceof Map) return (Map<String, Object>) v;
        throw new IllegalArgumentException("Expected JSON object");
    }

    private static final class Parser {
        final String src;
        int pos;

        Parser(String src) { this.src = src; pos = 0; }

        void skipWs() {
            while (pos < src.length() && Character.isWhitespace(src.charAt(pos))) pos++;
        }

        Object parseValue() {
            skipWs();
            if (pos >= src.length()) throw new IllegalArgumentException("Unexpected end of JSON");
            char c = src.charAt(pos);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't' || c == 'f') return parseBool();
            if (c == 'n') return parseNull();
            return parseNumber();
        }

        Map<String, Object> parseObject() {
            Map<String, Object> m = new LinkedHashMap<>();
            pos++; // {
            skipWs();
            if (pos < src.length() && src.charAt(pos) == '}') { pos++; return m; }
            while (true) {
                skipWs();
                if (pos >= src.length() || src.charAt(pos) != '"') {
                    throw new IllegalArgumentException("Expected string key at " + pos);
                }
                String key = parseString();
                skipWs();
                if (pos >= src.length() || src.charAt(pos) != ':') {
                    throw new IllegalArgumentException("Expected ':' at " + pos);
                }
                pos++;
                Object val = parseValue();
                m.put(key, val);
                skipWs();
                if (pos < src.length() && src.charAt(pos) == ',') { pos++; continue; }
                if (pos < src.length() && src.charAt(pos) == '}') { pos++; break; }
                throw new IllegalArgumentException("Expected ',' or '}' at " + pos);
            }
            return m;
        }

        java.util.List<Object> parseArray() {
            java.util.List<Object> list = new java.util.ArrayList<>();
            pos++; // [
            skipWs();
            if (pos < src.length() && src.charAt(pos) == ']') { pos++; return list; }
            while (true) {
                list.add(parseValue());
                skipWs();
                if (pos < src.length() && src.charAt(pos) == ',') { pos++; continue; }
                if (pos < src.length() && src.charAt(pos) == ']') { pos++; break; }
                throw new IllegalArgumentException("Expected ',' or ']' at " + pos);
            }
            return list;
        }

        String parseString() {
            if (src.charAt(pos) != '"') throw new IllegalArgumentException("Expected '\"' at " + pos);
            pos++;
            StringBuilder sb = new StringBuilder();
            while (pos < src.length()) {
                char c = src.charAt(pos++);
                if (c == '"') return sb.toString();
                if (c == '\\') {
                    if (pos >= src.length()) throw new IllegalArgumentException("Bad escape");
                    char esc = src.charAt(pos++);
                    switch (esc) {
                        case '"':  sb.append('"');  break;
                        case '\\': sb.append('\\'); break;
                        case '/':  sb.append('/');  break;
                        case 'b':  sb.append('\b'); break;
                        case 'f':  sb.append('\f'); break;
                        case 'n':  sb.append('\n'); break;
                        case 'r':  sb.append('\r'); break;
                        case 't':  sb.append('\t'); break;
                        case 'u':
                            if (pos + 4 > src.length()) throw new IllegalArgumentException("Bad \\u escape");
                            int cp = Integer.parseInt(src.substring(pos, pos + 4), 16);
                            sb.append((char) cp);
                            pos += 4;
                            break;
                        default: throw new IllegalArgumentException("Unknown escape \\" + esc);
                    }
                } else {
                    sb.append(c);
                }
            }
            throw new IllegalArgumentException("Unterminated string");
        }

        Boolean parseBool() {
            if (src.startsWith("true", pos))  { pos += 4; return Boolean.TRUE;  }
            if (src.startsWith("false", pos)) { pos += 5; return Boolean.FALSE; }
            throw new IllegalArgumentException("Invalid token at " + pos);
        }

        Object parseNull() {
            if (src.startsWith("null", pos)) { pos += 4; return null; }
            throw new IllegalArgumentException("Invalid token at " + pos);
        }

        Object parseNumber() {
            int start = pos;
            if (src.charAt(pos) == '-') pos++;
            while (pos < src.length() && Character.isDigit(src.charAt(pos))) pos++;
            boolean isFloat = false;
            if (pos < src.length() && src.charAt(pos) == '.') {
                isFloat = true;
                pos++;
                while (pos < src.length() && Character.isDigit(src.charAt(pos))) pos++;
            }
            if (pos < src.length() && (src.charAt(pos) == 'e' || src.charAt(pos) == 'E')) {
                isFloat = true;
                pos++;
                if (pos < src.length() && (src.charAt(pos) == '+' || src.charAt(pos) == '-')) pos++;
                while (pos < src.length() && Character.isDigit(src.charAt(pos))) pos++;
            }
            String s = src.substring(start, pos);
            if (isFloat) return Double.parseDouble(s);
            return Long.parseLong(s);
        }
    }

    // ---------------------------------------------------------------
    // Convenience
    // ---------------------------------------------------------------

    public static Map<String, Object> obj() {
        return new LinkedHashMap<>();
    }

    public static Map<String, Object> obj(Object... kv) {
        if (kv.length % 2 != 0) throw new IllegalArgumentException("obj() takes pairs");
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return m;
    }
}
