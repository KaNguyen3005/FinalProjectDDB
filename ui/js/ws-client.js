const API_ORIGIN = location.protocol === "file:" ? "http://127.0.0.1:8000" : location.origin;
const protocol = API_ORIGIN.startsWith("https:") ? "wss" : "ws";
const WS_URL = `${protocol}://${new URL(API_ORIGIN).host}/ws/events`;
const handlers = new Map();

let socket = null;

export function on(eventType, fn) {
  // Multiple screens can register callbacks for the same backend event type.
  if (!handlers.has(eventType)) {
    handlers.set(eventType, new Set());
  }
  handlers.get(eventType).add(fn);
}

export function connect() {
  // Reconnect automatically so a backend reload does not require page refresh.
  socket = new WebSocket(WS_URL);
  socket.onmessage = ({ data }) => {
    const event = JSON.parse(data);
    const callbacks = handlers.get(event.type) || [];
    callbacks.forEach((fn) => fn(event));
  };
  socket.onclose = () => {
    setTimeout(connect, 1500);
  };
  return socket;
}
