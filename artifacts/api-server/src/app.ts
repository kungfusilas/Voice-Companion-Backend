import express, { type Express, type Request, type Response } from "express";
import cors from "cors";
import pinoHttp from "pino-http";
import { fileURLToPath } from "url";
import router from "./routes";
import { logger } from "./lib/logger";

const app: Express = express();

app.use(
  pinoHttp({
    logger,
    serializers: {
      req(req) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Static pages — resolve from dist/ back up to workspace root
const LANDING_HTML = fileURLToPath(new URL("../../../landing.html", import.meta.url));
const TERMS_HTML   = fileURLToPath(new URL("../../../terms.html",   import.meta.url));

app.get("/", (_req, res) => { res.sendFile(LANDING_HTML); });
app.get("/terms", (_req, res) => { res.sendFile(TERMS_HTML); });

// Email verification — called when user clicks the link in the verification email.
// Supabase appends token_hash + type; we verify server-side and redirect into the app.
app.get("/verify-email", async (req: Request, res: Response) => {
  const token = (req.query["token_hash"] ?? req.query["token"]) as string | undefined;
  const type  = (req.query["type"] as string | undefined) ?? "email";

  const supabaseUrl = process.env["SUPABASE_URL"]?.replace(/\/$/, "");
  const serviceKey  = process.env["SUPABASE_SERVICE_KEY"];

  if (!token) {
    return res.redirect("/companion/?verified=error&reason=missing_token");
  }

  if (!supabaseUrl || !serviceKey) {
    logger.error("SUPABASE_URL or SUPABASE_SERVICE_KEY not set");
    return res.redirect("/companion/?verified=error&reason=config");
  }

  try {
    const response = await fetch(`${supabaseUrl}/auth/v1/verify`, {
      method: "POST",
      headers: {
        "apikey": serviceKey,
        "Authorization": `Bearer ${serviceKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ token_hash: token, type }),
    });

    if (response.ok) {
      return res.redirect("/companion/?verified=success");
    }

    const body = await response.json().catch(() => ({}));
    logger.warn({ status: response.status, body }, "Supabase verify failed");
    return res.redirect("/companion/?verified=error&reason=invalid_token");
  } catch (err) {
    logger.error({ err }, "Error calling Supabase verify");
    return res.redirect("/companion/?verified=error&reason=server_error");
  }
});

app.use("/api", router);

export default app;
