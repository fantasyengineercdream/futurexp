const ROOM_ORIGINS = new Set([
  "https://oc-voice.open.smn.icu",
  "http://127.0.0.1:4174",
  "http://localhost:4174",
]);

function corsHeaders(request) {
  const origin = request.headers.get("origin");
  if (!origin || !ROOM_ORIGINS.has(origin)) {
    return {};
  }
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-headers": "content-type",
    "access-control-allow-methods": "GET, POST, OPTIONS",
    vary: "Origin",
  };
}

function jsonResponse(request, body, status, extraHeaders = {}) {
  return Response.json(body, {
    status,
    headers: {
      "cache-control": "no-store",
      ...corsHeaders(request),
      ...extraHeaders,
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/api/")) {
      if (request.method === "OPTIONS") {
        return new Response(null, {
          status: 204,
          headers: {
            "cache-control": "no-store",
            ...corsHeaders(request),
          },
        });
      }

      if (!env.API_ORIGIN || !env.API_GATE_TOKEN) {
        return jsonResponse(
          request,
          {
            code: "LIVING_WORLD_PROXY_NOT_CONFIGURED",
            message: "The temporary Living World proxy is not configured.",
            retryable: true,
          },
          503,
        );
      }

      try {
        const upstreamUrl = new URL(
          `${url.pathname}${url.search}`,
          String(env.API_ORIGIN).trim(),
        );
        const upstreamRequest = new Request(upstreamUrl, request);
        const upstreamHeaders = new Headers(upstreamRequest.headers);
        upstreamHeaders.delete("origin");
        upstreamHeaders.set(
          "x-oocc-test-gate",
          String(env.API_GATE_TOKEN).trim(),
        );

        const upstreamResponse = await fetch(
          new Request(upstreamRequest, { headers: upstreamHeaders }),
        );
        const headers = new Headers(upstreamResponse.headers);
        headers.set("cache-control", "no-store");
        headers.set("x-oocc-world-source", "live-tunnel");
        for (const [name, value] of Object.entries(corsHeaders(request))) {
          headers.set(name, value);
        }

        return new Response(upstreamResponse.body, {
          status: upstreamResponse.status,
          statusText: upstreamResponse.statusText,
          headers,
        });
      } catch {
        return jsonResponse(
          request,
          {
            code: "LIVING_WORLD_ORIGIN_UNAVAILABLE",
            message:
              "The temporary Living World test origin is offline. Keep the demo laptop and API service running.",
            retryable: true,
          },
          502,
          { "x-oocc-world-source": "offline" },
        );
      }
    }

    return env.ASSETS.fetch(request);
  },
};
