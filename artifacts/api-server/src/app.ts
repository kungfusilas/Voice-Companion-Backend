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
const LANDING_HTML  = fileURLToPath(new URL("../../../landing.html",  import.meta.url));
const TERMS_HTML    = fileURLToPath(new URL("../../../terms.html",    import.meta.url));
const PRIVACY_HTML  = fileURLToPath(new URL("../../../privacy.html",  import.meta.url));

app.get("/", (_req, res) => { res.sendFile(LANDING_HTML); });
app.get("/terms",   (_req, res) => { res.sendFile(TERMS_HTML); });
app.get("/privacy", (_req, res) => { res.sendFile(PRIVACY_HTML); });

// Email verification — called when user clicks the link in the verification email.
// Supabase appends token_hash + type; we verify server-side, then redirect into the
// app with the session tokens in the URL hash so the Supabase JS client picks them
// up automatically via detectSessionInUrl and logs the user in without a second step.
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

    const body = await response.json().catch(() => ({})) as Record<string, unknown>;

    if (!response.ok) {
      logger.warn({ status: response.status, body }, "Supabase verify failed");
      return res.redirect("/companion/?verified=error&reason=invalid_token");
    }

    // Supabase returns access_token + refresh_token on success.
    // Putting them in the URL hash lets the Supabase JS client (detectSessionInUrl)
    // automatically establish the session — user lands logged in, no second sign-in.
    const accessToken  = body["access_token"]  as string | undefined;
    const refreshToken = body["refresh_token"] as string | undefined;
    const tokenType    = (body["token_type"]   as string | undefined) ?? "bearer";

    if (accessToken && refreshToken) {
      const hash = new URLSearchParams({
        access_token:  accessToken,
        refresh_token: refreshToken,
        token_type:    tokenType,
        type:          "signup",
      }).toString().replace(/\+/g, "%20");
      return res.redirect(`/companion/#${hash}`);
    }

    // Tokens missing in response — fall back to the auth screen with a success hint
    logger.warn({ body }, "Supabase verify OK but no tokens in response");
    return res.redirect("/companion/?verified=success");
  } catch (err) {
    logger.error({ err }, "Error calling Supabase verify");
    return res.redirect("/companion/?verified=error&reason=server_error");
  }
});

app.use("/api", router);

export default app;
