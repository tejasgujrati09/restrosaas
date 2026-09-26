// Development only. One port in front of the API and the staff app, so a single tunnel
// (ngrok free plan: one domain) can serve both from one origin.
//   /v1/*, /health, /docs, /openapi.json  -> API
//   everything else                       -> staff app (including its hot-reload socket)
import http from "node:http";
import net from "node:net";

const [listen, api, staff] = [process.argv[2] ?? 8080, process.argv[3] ?? 8001, process.argv[4] ?? 3001].map(Number);
const toApi = (url = "") => /^\/(v1\/|health|docs|openapi\.json)/.test(url);
const port = (url) => (toApi(url) ? api : staff);

const server = http.createServer((req, res) => {
  const upstream = http.request(
    { host: "127.0.0.1", port: port(req.url), path: req.url, method: req.method, headers: req.headers },
    (r) => { res.writeHead(r.statusCode ?? 502, r.headers); r.pipe(res); },
  );
  upstream.on("error", () => { res.writeHead(502); res.end("upstream unavailable"); });
  req.pipe(upstream);
});

server.on("upgrade", (req, socket, head) => {
  const up = net.connect(port(req.url), "127.0.0.1", () => {
    const lines = [`${req.method} ${req.url} HTTP/1.1`];
    for (let i = 0; i < req.rawHeaders.length; i += 2) lines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
    up.write(lines.join("\r\n") + "\r\n\r\n");
    up.write(head);
    socket.pipe(up).pipe(socket);
  });
  up.on("error", () => socket.destroy());
  socket.on("error", () => up.destroy());
});

server.listen(listen, "127.0.0.1", () => console.log(`proxy on :${listen} -> api :${api}, staff :${staff}`));
