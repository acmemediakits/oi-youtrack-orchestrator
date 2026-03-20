from __future__ import annotations

import html
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import FastAPI, Form, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.dependencies import (
    get_admin_approval_service,
    get_commit_service,
    get_issue_subscription_service,
    get_mail_automation_runner,
    get_mail_automation_service,
    get_mailbox_service,
    get_openwebui_client,
    get_permission_service,
    get_preview_service,
    get_query_service,
    get_request_repository,
    get_request_service,
    get_runtime_config_service,
    get_user_directory_service,
    get_youtrack_client,
)
from app.logging_utils import get_log_file_path, get_recent_logs, setup_logging
from app.models import (
    AssistantProjectContext,
    ArticleSearchResult,
    CommitInput,
    CommitResult,
    GlobalTimeTrackingSummary,
    IngestRequestInput,
    IssueEditInput,
    IssueSearchResult,
    MailProcessingRecord,
    MailboxMessage,
    NormalizedRequest,
    RuntimeMailboxFolders,
    PreviewInput,
    ProjectSearchResult,
    TimeTrackingSummary,
    WhitelistedUser,
    UserType,
    WorkItemCreateInput,
    WorkItemEditInput,
)

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        get_mailbox_service().ensure_runtime_folders()
    except Exception:
        logger.exception("IMAP folder bootstrap failed during startup.")
    runner = get_mail_automation_runner()
    runner.start()
    try:
        yield
    finally:
        await runner.stop()


app = FastAPI(
    title="YouTrack Open WebUI Orchestrator",
    version="0.1.0",
    description="OpenAPI backend for issue, time tracking, knowledge base and request triage workflows.",
    lifespan=lifespan,
)


def _panel_cookie_value() -> str:
    return hashlib.sha256(settings.panel_admin_password.encode("utf-8")).hexdigest() if settings.panel_admin_password else ""


def _panel_authenticated(request: Request) -> bool:
    cookie = request.cookies.get("panel_auth")
    expected = _panel_cookie_value()
    return bool(expected and cookie and hmac.compare_digest(cookie, expected))


def _require_panel_auth(request: Request) -> None:
    if not _panel_authenticated(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, detail="Panel auth required.")


def _resolve_actor(actor_email: str | None):
    if not actor_email:
        raise HTTPException(status_code=401, detail="Missing X-Actor-Email header.")
    user = get_user_directory_service().resolve(actor_email)
    try:
        return get_permission_service().ensure_active_user(user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _assert_capability(actor, capability: str) -> None:
    try:
        get_permission_service().assert_capability(actor, capability)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _assert_issue_edit_allowed(actor, issue_id: str) -> None:
    if actor.user_type == UserType.visitor and not get_permission_service().can_modify_issue(actor, issue_id):
        raise HTTPException(status_code=403, detail="Il visitor puo' modificare solo i ticket creati da lui negli ultimi 30 minuti.")


def _panel_css() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #dde5ff;
      --bg-accent: #d4dafe;
      --surface: rgba(255, 255, 255, 0.78);
      --surface-strong: rgba(255, 255, 255, 0.96);
      --surface-muted: rgba(240, 243, 255, 0.92);
      --text: #18243f;
      --muted: #5b6788;
      --border: rgba(108, 129, 203, 0.22);
      --shadow: 0 24px 80px rgba(72, 79, 154, 0.16);
      --brand: #6f84d8;
      --brand-strong: #5267b8;
      --brand-soft: rgba(111, 132, 216, 0.16);
      --success: #166534;
      --success-soft: rgba(34, 197, 94, 0.16);
      --danger: #b91c1c;
      --danger-soft: rgba(239, 68, 68, 0.14);
      --info: #3857c8;
      --info-soft: rgba(86, 114, 222, 0.16);
      --radius-lg: 28px;
      --radius-md: 18px;
      --radius-sm: 12px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Inter", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(255, 255, 255, 0.32), transparent 24%),
        radial-gradient(circle at right 12%, rgba(183, 136, 207, 0.20), transparent 22%),
        linear-gradient(135deg, #6f86c9 0%, #7b7ec0 42%, #9a6cae 100%);
    }
    a { color: inherit; }
    .shell {
      width: min(1200px, calc(100vw - 32px));
      margin: 32px auto;
      position: relative;
    }
    .glass,
    .metric,
    .panel-card,
    .table-card,
    .login-card {
      border: 1px solid var(--border);
      background: var(--surface);
      backdrop-filter: blur(18px);
      box-shadow: var(--shadow);
    }
    .hero {
      display: flex;
      gap: 24px;
      justify-content: space-between;
      align-items: flex-start;
      padding: 28px;
      border-radius: var(--radius-lg);
      overflow: hidden;
      position: relative;
    }
    .hero::after {
      content: "";
      position: absolute;
      inset: auto -40px -55px auto;
      width: 240px;
      height: 240px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(162, 122, 200, 0.24), transparent 68%);
      pointer-events: none;
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--brand-soft);
      color: var(--brand-strong);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    h1, h2, h3, h4, p { margin: 0; }
    .hero h1 {
      margin-top: 14px;
      font-size: clamp(2rem, 3vw, 3.3rem);
      line-height: 0.96;
      letter-spacing: -0.05em;
      max-width: 12ch;
    }
    .hero p {
      margin-top: 14px;
      max-width: 60ch;
      color: var(--muted);
      line-height: 1.6;
      font-size: 15px;
    }
    .hero-actions {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 14px;
      min-width: 240px;
    }
    .status-pill,
    .role-pill,
    .secret-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.01em;
      white-space: nowrap;
      border: 1px solid transparent;
    }
    .status-pill.good,
    .role-pill.role-power,
    .secret-pill.good {
      background: var(--success-soft);
      color: var(--success);
      border-color: rgba(34, 197, 94, 0.12);
    }
    .status-pill.warn,
    .role-pill.role-team {
      background: var(--info-soft);
      color: var(--info);
      border-color: rgba(59, 130, 246, 0.12);
    }
    .status-pill.bad,
    .role-pill.role-visitor,
    .secret-pill.bad {
      background: var(--danger-soft);
      color: var(--danger);
      border-color: rgba(239, 68, 68, 0.12);
    }
    .hero-meta {
      display: grid;
      gap: 10px;
      justify-items: end;
      text-align: right;
      color: var(--muted);
      font-size: 14px;
    }
    .hero-meta strong {
      display: block;
      color: var(--text);
      font-size: 15px;
    }
    .logout-form { margin: 0; }
    .grid-metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 18px;
      margin-top: 22px;
    }
    .metric {
      border-radius: 24px;
      padding: 22px;
    }
    .metric .label {
      font-size: 13px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-weight: 700;
    }
    .metric .value {
      margin-top: 10px;
      font-size: clamp(1.7rem, 2.1vw, 2.4rem);
      font-weight: 800;
      letter-spacing: -0.04em;
    }
    .metric .detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }
    .metric.highlight {
      background: linear-gradient(160deg, rgba(245, 247, 255, 0.96), rgba(255, 255, 255, 0.84));
    }
    .stack {
      display: grid;
      gap: 20px;
      margin-top: 22px;
    }
    .panel-card,
    .table-card {
      border-radius: var(--radius-lg);
      padding: 24px;
    }
    .card-head {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 18px;
    }
    .card-head p {
      margin-top: 8px;
      color: var(--muted);
      line-height: 1.55;
      font-size: 14px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    .field,
    .field-full {
      display: grid;
      gap: 8px;
    }
    .field-full {
      grid-column: 1 / -1;
    }
    label span {
      font-size: 13px;
      font-weight: 700;
      color: var(--muted);
    }
    input[type="text"],
    input[type="email"],
    input[type="password"],
    input[type="number"],
    select {
      width: 100%;
      border: 1px solid rgba(148, 163, 184, 0.24);
      background: var(--surface-strong);
      border-radius: 14px;
      padding: 13px 14px;
      font-size: 15px;
      color: var(--text);
      outline: none;
      transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
    }
    input:focus,
    select:focus {
      border-color: rgba(180, 83, 9, 0.45);
      box-shadow: 0 0 0 5px rgba(111, 132, 216, 0.16);
      transform: translateY(-1px);
    }
    .checkbox-field {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 14px 16px;
      border-radius: 14px;
      background: var(--surface-muted);
      border: 1px solid rgba(148, 163, 184, 0.18);
      min-height: 52px;
    }
    .checkbox-field input {
      width: 18px;
      height: 18px;
      accent-color: var(--brand);
    }
    .checkbox-field span {
      font-size: 14px;
      font-weight: 600;
      color: var(--text);
    }
    .btn-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-top: 18px;
      flex-wrap: wrap;
    }
    .btn,
    button {
      appearance: none;
      border: 0;
      border-radius: 14px;
      padding: 12px 18px;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
      transition: transform 140ms ease, box-shadow 140ms ease, opacity 140ms ease;
      text-decoration: none;
    }
    .btn:hover,
    button:hover {
      transform: translateY(-1px);
      box-shadow: 0 16px 34px rgba(15, 23, 42, 0.12);
    }
    .btn-primary,
    button[type="submit"] {
      background: linear-gradient(135deg, var(--brand) 0%, #8f6fc7 100%);
      color: white;
    }
    .btn-secondary {
      background: rgba(255, 255, 255, 0.76);
      color: var(--text);
      border: 1px solid rgba(148, 163, 184, 0.24);
    }
    .hint {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.58);
    }
    th, td {
      padding: 14px 16px;
      text-align: left;
      border-bottom: 1px solid rgba(148, 163, 184, 0.14);
      vertical-align: middle;
      font-size: 14px;
    }
    th {
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      background: rgba(248, 250, 252, 0.9);
    }
    tr:last-child td {
      border-bottom: 0;
    }
    .user-meta strong {
      display: block;
      font-size: 15px;
      color: var(--text);
      margin-bottom: 4px;
    }
    .user-meta span {
      color: var(--muted);
      font-size: 13px;
    }
    .secrets-list {
      display: grid;
      gap: 12px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .secret-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      background: rgba(255, 255, 255, 0.62);
      border: 1px solid rgba(148, 163, 184, 0.16);
      border-radius: 16px;
    }
    .secret-item strong {
      display: block;
      font-size: 14px;
      margin-bottom: 4px;
    }
    .secret-item span {
      color: var(--muted);
      font-size: 13px;
    }
    .login-wrap {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .login-card {
      width: min(520px, 100%);
      border-radius: 32px;
      padding: 32px;
      position: relative;
      overflow: hidden;
    }
    .login-card::before {
      content: "";
      position: absolute;
      inset: auto auto -70px -55px;
      width: 220px;
      height: 220px;
      background: radial-gradient(circle, rgba(180, 83, 9, 0.16), transparent 66%);
      pointer-events: none;
    }
    .login-card h1 {
      margin-top: 18px;
      font-size: clamp(2rem, 5vw, 2.8rem);
      line-height: 0.96;
      letter-spacing: -0.05em;
      max-width: 10ch;
    }
    .login-card p {
      margin-top: 14px;
      color: var(--muted);
      line-height: 1.6;
    }
    .login-form {
      margin-top: 24px;
      display: grid;
      gap: 16px;
    }
    .alert {
      margin-top: 18px;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid rgba(239, 68, 68, 0.18);
      background: rgba(254, 242, 242, 0.88);
      color: var(--danger);
      font-size: 14px;
      line-height: 1.5;
    }
    .footer-note {
      margin-top: 18px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    .brand-credits {
      margin-top: 18px;
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .brand-credits a {
      color: var(--brand-strong);
      text-decoration: none;
      font-weight: 700;
    }
    .brand-credits a:hover {
      text-decoration: underline;
    }
    .table-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .link-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--brand-soft);
      color: var(--brand-strong);
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
      transition: transform 140ms ease, opacity 140ms ease;
    }
    .link-btn:hover {
      transform: translateY(-1px);
      opacity: 0.92;
    }
    .subtle-banner {
      margin-bottom: 16px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(111, 132, 216, 0.10);
      border: 1px solid rgba(111, 132, 216, 0.18);
      color: var(--text);
      font-size: 14px;
      line-height: 1.5;
    }
    .section-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .accordion {
      border-radius: var(--radius-lg);
      overflow: hidden;
    }
    .accordion summary {
      list-style: none;
      cursor: pointer;
    }
    .accordion summary::-webkit-details-marker {
      display: none;
    }
    .accordion-body {
      margin-top: 18px;
    }
    .accordion-label {
      color: var(--muted);
      font-size: 14px;
      margin-top: 8px;
      line-height: 1.55;
    }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(24, 36, 63, 0.42);
      backdrop-filter: blur(8px);
      display: grid;
      place-items: center;
      padding: 20px;
      z-index: 50;
    }
    .modal-card {
      width: min(720px, 100%);
      max-height: calc(100vh - 40px);
      overflow: auto;
      border-radius: 30px;
      padding: 26px;
    }
    .page-dimmed {
      filter: blur(2px);
      pointer-events: none;
      user-select: none;
    }
    .log-console {
      margin-top: 16px;
      padding: 18px;
      border-radius: 18px;
      background: #19233f;
      color: #dbe7ff;
      font-family: "SFMono-Regular", "SF Mono", Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 420px;
      overflow: auto;
      border: 1px solid rgba(111, 132, 216, 0.22);
    }
    .log-meta {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
    }
    @media (max-width: 1024px) {
      .grid-metrics,
      .form-grid {
        grid-template-columns: 1fr 1fr;
      }
      .hero {
        flex-direction: column;
      }
      .hero-actions,
      .hero-meta {
        align-items: flex-start;
        text-align: left;
      }
    }
    @media (max-width: 720px) {
      .shell {
        width: min(100vw - 20px, 100%);
        margin: 18px auto;
      }
      .hero,
      .panel-card,
      .table-card,
      .login-card,
      .metric {
        padding: 20px;
        border-radius: 22px;
      }
      .grid-metrics,
      .form-grid {
        grid-template-columns: 1fr;
      }
      th, td {
        padding: 12px;
      }
      .table-card {
        overflow-x: auto;
      }
      .modal-card {
        padding: 20px;
        border-radius: 22px;
      }
    }
    """


def _escape(value: object | None) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _format_panel_datetime(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return value.astimezone().strftime("%d %b %Y, %H:%M")


def _status_pill(label: str, tone: str) -> str:
    return f"<span class='status-pill {tone}'>{_escape(label)}</span>"


def _role_pill(role: UserType) -> str:
    return f"<span class='role-pill role-{_escape(role.value)}'>{_escape(role.value)}</span>"


def _render_login_page(error_message: str | None = None) -> str:
    alert = f"<div class='alert'>{_escape(error_message)}</div>" if error_message else ""
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>OI Control Panel Login</title>
      <style>{_panel_css()}</style>
    </head>
    <body>
      <main class="login-wrap">
        <section class="login-card">
          <span class="eyebrow">Operations Console</span>
          <h1>Sign in to the OI control panel</h1>
          <p>Runtime settings, whitelist users and service readiness in one client-friendly dashboard.</p>
          {alert}
          <form class="login-form" method="post" action="/panel/login">
            <label class="field-full">
              <span>Admin password</span>
              <input type="password" name="password" placeholder="Enter panel password" autocomplete="current-password" required>
            </label>
            <button class="btn btn-primary" type="submit">Open dashboard</button>
          </form>
          <div class="brand-credits">
            <span>Crafted with Acme Media Kits for client-facing operations.</span>
            <span><a href="https://www.acmemk.com" target="_blank" rel="noreferrer">acmemk.com</a> · <a href="https://chatnorris.it" target="_blank" rel="noreferrer">chatnorris.it</a></span>
          </div>
          <p class="footer-note">Authentication uses the configured <code>PANEL_ADMIN_PASSWORD</code> and an HTTP-only session cookie.</p>
        </section>
      </main>
    </body>
    </html>
    """


def _render_user_modal(editing_user: WhitelistedUser | None = None) -> str:
    editing = editing_user is not None
    form_title = "Edit user" if editing else "Add user"
    form_copy = "Update an existing whitelist entry, including canonical email changes." if editing else "Create a new whitelist entry for internal operations and client onboarding."
    form_button = "Save changes" if editing else "Save user"
    form_hint = "Changing the canonical email now updates the existing profile instead of creating a duplicate." if editing else "If assignee email is empty, the backend falls back to the configured default developer mailbox."
    edit_banner = (
        f"<div class='subtle-banner'>Editing <strong>{_escape(editing_user.full_name)}</strong> ({_escape(editing_user.email)}). "
        "You can update role, status, assignee email and canonical email from this form.</div>"
        if editing_user
        else ""
    )
    return f"""
    <div class="modal-backdrop">
      <section class="panel-card modal-card">
        <div class="card-head">
          <div>
            <h2>{form_title}</h2>
            <p>{form_copy}</p>
          </div>
          <a class="link-btn" href="/panel">Close</a>
        </div>
        {edit_banner}
        <form method="post" action="/panel/users">
          <input type="hidden" name="original_email" value="{_escape(editing_user.email if editing_user else '')}">
          <div class="form-grid">
            <label class="field-full">
              <span>Full name</span>
              <input type="text" name="full_name" placeholder="Jane Doe" value="{_escape(editing_user.full_name if editing_user else '')}" required>
            </label>
            <label class="field-full">
              <span>Canonical email</span>
              <input type="email" name="email" placeholder="jane.doe@acmemk.com" value="{_escape(editing_user.email if editing_user else '')}" required>
            </label>
            <label class="field-full">
              <span>YouTrack assignee email</span>
              <input type="email" name="youtrack_assignee_email" value="{_escape(editing_user.youtrack_assignee_email if editing_user else '')}" placeholder="{_escape(settings.youtrack_default_assignee_email or 'developers@acmemk.com')}">
            </label>
            <label class="field">
              <span>Role</span>
              <select name="user_type" required>
                <option value="visitor" {'selected' if (editing_user and editing_user.user_type == UserType.visitor) or not editing_user else ''}>visitor</option>
                <option value="team" {'selected' if editing_user and editing_user.user_type == UserType.team else ''}>team</option>
                <option value="power" {'selected' if editing_user and editing_user.user_type == UserType.power else ''}>power</option>
              </select>
            </label>
            <label class="checkbox-field">
              <input type="checkbox" name="active" {'checked' if (editing_user is None or editing_user.active) else ''}>
              <span>User is active and allowed to operate</span>
            </label>
          </div>
          <div class="btn-row">
            <p class="hint">{form_hint}</p>
            <div class="table-actions">
              <a class="link-btn" href="/panel">Cancel</a>
              <button class="btn btn-primary" type="submit">{form_button}</button>
            </div>
          </div>
        </form>
      </section>
    </div>
    """


def _render_panel(
    status_model,
    users: list,
    editing_user: WhitelistedUser | None = None,
    show_user_modal: bool = False,
    recent_logs: list[str] | None = None,
    log_path: str = "",
) -> str:
    runtime_config = status_model.runtime_config
    domains = ", ".join(runtime_config.mailbox_allowed_sender_domains)
    configured_secrets = sum(1 for value in status_model.secrets_status.values() if value)
    missing_secrets = len(status_model.secrets_status) - configured_secrets
    inactive_users = status_model.users_total - status_model.users_active
    rendered_logs = "\n".join(recent_logs or ["No log entries captured yet."])
    user_rows = "\n".join(
        (
            "<tr>"
            f"<td><div class='user-meta'><strong>{_escape(user.full_name)}</strong><span>{_escape(user.email)}</span></div></td>"
            f"<td>{_role_pill(user.user_type)}</td>"
            f"<td>{_escape(user.youtrack_assignee_email or settings.youtrack_default_assignee_email or 'Not set')}</td>"
            f"<td>{_status_pill('active' if user.active else 'inactive', 'good' if user.active else 'bad')}</td>"
            f"<td>{_escape(_format_panel_datetime(user.updated_at))}</td>"
            f"<td><div class='table-actions'><a class='link-btn' href='/panel?user_modal=edit&amp;edit_email={_escape(user.email)}'>Edit</a></div></td>"
            "</tr>"
        )
        for user in users
    ) or "<tr><td colspan='6'>No users configured yet.</td></tr>"
    secret_rows = "".join(
        (
            "<li class='secret-item'>"
            f"<div><strong>{_escape(key.replace('_', ' ').replace(' configured', '').title())}</strong>"
            f"<span>{'Ready for production use' if value else 'Missing configuration in environment'}</span></div>"
            f"<span class='secret-pill {'good' if value else 'bad'}'>{'Configured' if value else 'Missing'}</span>"
            "</li>"
        )
        for key, value in status_model.secrets_status.items()
    )
    user_modal = _render_user_modal(editing_user) if show_user_modal else ""
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>OI Control Panel</title>
      <style>{_panel_css()}</style>
    </head>
    <body>
      <main class="shell {'page-dimmed' if show_user_modal else ''}">
        <section class="hero glass">
          <div>
            <span class="eyebrow">Client-ready dashboard</span>
            <h1>OI control panel for runtime and access governance</h1>
            <p>Manage mailbox orchestration settings, monitor environment readiness and curate the user whitelist without touching deployment files.</p>
          </div>
          <div class="hero-actions">
            {_status_pill('System ready' if missing_secrets == 0 else f'{missing_secrets} secrets missing', 'good' if missing_secrets == 0 else 'bad')}
            <div class="hero-meta">
              <div><strong>Runtime updated</strong>{_escape(_format_panel_datetime(runtime_config.updated_at))}</div>
              <div><strong>Mailbox cadence</strong>Every {_escape(runtime_config.mailbox_poll_interval_seconds)} seconds</div>
              <form class="logout-form" method="post" action="/panel/logout">
                <button class="btn btn-secondary" type="submit">Logout</button>
              </form>
            </div>
          </div>
        </section>

        <section class="grid-metrics">
          <article class="metric highlight">
            <div class="label">Active users</div>
            <div class="value">{_escape(status_model.users_active)} / {_escape(status_model.users_total)}</div>
            <div class="detail">Whitelist coverage across visitor, team and power roles.</div>
          </article>
          <article class="metric">
            <div class="label">Inactive users</div>
            <div class="value">{_escape(inactive_users)}</div>
            <div class="detail">Profiles kept on record but blocked from actions and API enforcement.</div>
          </article>
          <article class="metric">
            <div class="label">Secrets configured</div>
            <div class="value">{_escape(configured_secrets)} / {_escape(len(status_model.secrets_status))}</div>
            <div class="detail">Bootstrapped from environment variables only.</div>
          </article>
          <article class="metric">
            <div class="label">Allowed domains</div>
            <div class="value">{_escape(len(runtime_config.mailbox_allowed_sender_domains))}</div>
            <div class="detail">Inbound email senders accepted by the mailbox automation.</div>
          </article>
        </section>

        <section class="stack">
          <section class="table-card">
            <div class="section-toolbar">
              <div class="card-head">
                <div>
                  <h2>Whitelisted users</h2>
                  <p>Canonical email identity, YouTrack fallback assignee and base role mapping for API and email-originated workflows.</p>
                </div>
                {_status_pill('Healthy roster' if status_model.users_active else 'No active users', 'good' if status_model.users_active else 'bad')}
              </div>
              <a class="btn btn-primary" href="/panel?user_modal=add">Add user</a>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Role</th>
                  <th>YouTrack assignee</th>
                  <th>Status</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {user_rows}
              </tbody>
            </table>
          </section>

          <details class="panel-card accordion">
            <summary>
              <div class="section-toolbar">
                <div>
                  <h2>Runtime settings</h2>
                  <p class="accordion-label">Editable JSON-backed configuration for mailbox behavior and general verbosity, separated from secrets and bootstrap values.</p>
                </div>
                {_status_pill('Verbose on' if runtime_config.verbose else 'Verbose off', 'warn' if runtime_config.verbose else 'good')}
              </div>
            </summary>
            <div class="accordion-body">
              <form method="post" action="/panel/settings">
                <div class="form-grid">
                  <label class="field">
                    <span>Poll interval (seconds)</span>
                    <input type="number" name="mailbox_poll_interval_seconds" min="10" max="86400" value="{_escape(runtime_config.mailbox_poll_interval_seconds)}" required>
                  </label>
                  <label class="field">
                    <span>Allowed sender domains</span>
                    <input type="text" name="mailbox_allowed_sender_domains" value="{_escape(domains)}" placeholder="acmemk.com, webme.it">
                  </label>
                  <label class="field">
                    <span>Inbox</span>
                    <input type="text" name="inbox" value="{_escape(runtime_config.mailbox_folders.inbox)}" required>
                  </label>
                  <label class="field">
                    <span>Processing</span>
                    <input type="text" name="processing" value="{_escape(runtime_config.mailbox_folders.processing)}" required>
                  </label>
                  <label class="field">
                    <span>Processed</span>
                    <input type="text" name="processed" value="{_escape(runtime_config.mailbox_folders.processed)}" required>
                  </label>
                  <label class="field">
                    <span>Failed</span>
                    <input type="text" name="failed" value="{_escape(runtime_config.mailbox_folders.failed)}" required>
                  </label>
                  <label class="field">
                    <span>Rejected</span>
                    <input type="text" name="rejected" value="{_escape(runtime_config.mailbox_folders.rejected)}" required>
                  </label>
                  <label class="checkbox-field">
                    <input type="checkbox" name="verbose" {'checked' if runtime_config.verbose else ''}>
                    <span>Enable verbose logs for runtime troubleshooting</span>
                  </label>
                </div>
                <div class="btn-row">
                  <p class="hint">These values are stored in <code>data/</code> runtime JSON, not in <code>.env</code>.</p>
                  <button class="btn btn-primary" type="submit">Save settings</button>
                </div>
              </form>
            </div>
          </details>

          <details class="panel-card accordion">
            <summary>
              <div class="section-toolbar">
                <div>
                  <h2>Bootstrap secret status</h2>
                  <p class="accordion-label">Environment-only values required for integrations, panel access and admin approval routing.</p>
                </div>
                {_status_pill('All configured' if missing_secrets == 0 else f'{missing_secrets} missing', 'good' if missing_secrets == 0 else 'bad')}
              </div>
            </summary>
            <div class="accordion-body">
              <ul class="secrets-list">
                {secret_rows}
              </ul>
            </div>
          </details>

          <details class="panel-card accordion" open>
            <summary>
              <div class="section-toolbar">
                <div>
                  <h2>Recent application logs</h2>
                  <p class="accordion-label">Live debugging view for IMAP bootstrap, mailbox polling, Open WebUI parsing and panel actions.</p>
                </div>
                {_status_pill('Live view', 'warn')}
              </div>
            </summary>
            <div class="accordion-body">
              <div class="log-console">{_escape(rendered_logs)}</div>
              <div class="log-meta">
                <span>Showing recent in-memory log lines from the running process.</span>
                <span>File: {_escape(log_path)}</span>
              </div>
            </div>
          </details>
        </section>
        <footer class="brand-credits">
          <span>Powered by Acme Media Kits. OI panel styling aligned with the Acme brand system.</span>
          <span><a href="https://www.acmemk.com" target="_blank" rel="noreferrer">acmemk.com</a> · <a href="https://chatnorris.it" target="_blank" rel="noreferrer">chatnorris.it</a></span>
        </footer>
      </main>
      {user_modal}
    </body>
    </html>
    """


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/panel/login", response_class=HTMLResponse)
async def panel_login_page(error: str | None = None) -> HTMLResponse:
    error_message = "Invalid panel password. Please try again." if error == "invalid" else None
    return HTMLResponse(_render_login_page(error_message))


@app.post("/panel/login")
async def panel_login(password: str = Form(...)) -> Response:
    if not settings.panel_admin_password or not hmac.compare_digest(password, settings.panel_admin_password):
        return RedirectResponse("/panel/login?error=invalid", status_code=status.HTTP_303_SEE_OTHER)
    response = RedirectResponse("/panel", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("panel_auth", _panel_cookie_value(), httponly=True, samesite="lax")
    return response


@app.post("/panel/logout")
async def panel_logout() -> Response:
    response = RedirectResponse("/panel/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("panel_auth")
    return response


@app.get("/panel", response_class=HTMLResponse)
async def panel_home(
    request: Request,
    edit_email: str | None = None,
    user_modal: str | None = None,
    log_lines: int = 120,
) -> HTMLResponse:
    if not _panel_authenticated(request):
        return HTMLResponse("", status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/panel/login"})
    user_service = get_user_directory_service()
    users = user_service.list_users()
    editing_user = user_service.resolve(edit_email) if edit_email else None
    show_user_modal = user_modal == "add" or (user_modal == "edit" and editing_user is not None)
    status_model = get_runtime_config_service().panel_status(users)
    log_lines = max(20, min(log_lines, 400))
    return HTMLResponse(
        _render_panel(
            status_model,
            users,
            editing_user,
            show_user_modal,
            recent_logs=get_recent_logs(log_lines),
            log_path=str(get_log_file_path()),
        )
    )


@app.post("/panel/settings")
async def panel_save_settings(
    request: Request,
    mailbox_poll_interval_seconds: int = Form(...),
    mailbox_allowed_sender_domains: str = Form(""),
    inbox: str = Form(...),
    processing: str = Form(...),
    processed: str = Form(...),
    failed: str = Form(...),
    rejected: str = Form(...),
    verbose: str | None = Form(None),
) -> Response:
    if not _panel_authenticated(request):
        raise HTTPException(status_code=403, detail="Panel auth required.")
    get_runtime_config_service().update(
        verbose=verbose is not None,
        mailbox_poll_interval_seconds=mailbox_poll_interval_seconds,
        mailbox_allowed_sender_domains=[item.strip().lower() for item in mailbox_allowed_sender_domains.split(",") if item.strip()],
        mailbox_folders=RuntimeMailboxFolders(
            inbox=inbox.strip(),
            processing=processing.strip(),
            processed=processed.strip(),
            failed=failed.strip(),
            rejected=rejected.strip(),
        ),
    )
    return RedirectResponse("/panel", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/panel/users")
async def panel_save_user(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    original_email: str = Form(""),
    youtrack_assignee_email: str = Form(""),
    user_type: UserType = Form(...),
    active: str | None = Form(None),
) -> Response:
    if not _panel_authenticated(request):
        raise HTTPException(status_code=403, detail="Panel auth required.")
    get_user_directory_service().upsert_user(
        full_name=full_name,
        email=email,
        original_email=original_email,
        youtrack_assignee_email=youtrack_assignee_email,
        user_type=user_type,
        active=active is not None,
    )
    return RedirectResponse("/panel", status_code=status.HTTP_303_SEE_OTHER)


@app.get(
    "/test",
    summary="Run external integration tests",
    description="Test Open WebUI connectivity, SMTP delivery, or both through simple query parameters.",
)
async def run_test(
    heartbeat: str | None = None,
    mailto: str | None = None,
    mailjoke: str | None = None,
) -> dict:
    if sum(value is not None for value in [heartbeat, mailto, mailjoke]) != 1:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of heartbeat, mailto, or mailjoke.",
        )

    mailbox = get_mail_automation_service().mailbox
    openwebui = get_openwebui_client()

    if heartbeat is not None:
        prompt = (
            "Reply with exactly one short joke in plain text. "
            f"Context token: {heartbeat}"
        )
        try:
            reply = await openwebui.generate_reply(prompt)
            return {
                "mode": "heartbeat",
                "openwebui_ok": True,
                "reply": reply,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Open WebUI heartbeat failed: {exc}") from exc

    if mailto is not None:
        try:
            message = MailboxMessage(
                message_id="test-mailto",
                mailbox_uid="0",
                sender=mailto,
                subject="YouTrack orchestrator SMTP test",
                text="SMTP test",
                received_at=datetime.now(timezone.utc),
            )
            mailbox.send_reply(
                message,
                "This is a direct SMTP test from the YouTrack Open WebUI orchestrator.",
            )
            return {
                "mode": "mailto",
                "smtp_ok": True,
                "recipient": mailto,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"SMTP test failed: {exc}") from exc

    try:
        prompt = "Reply with exactly one short joke in plain text."
        reply = await openwebui.generate_reply(prompt)
        message = MailboxMessage(
            message_id="test-mailjoke",
            mailbox_uid="0",
            sender=mailjoke or "",
            subject="YouTrack orchestrator mailjoke test",
            text="mailjoke test",
            received_at=datetime.now(timezone.utc),
        )
        mailbox.send_reply(message, reply)
        return {
            "mode": "mailjoke",
            "openwebui_ok": True,
            "smtp_ok": True,
            "recipient": mailjoke,
            "reply": reply,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"mailjoke test failed: {exc}") from exc


@app.post("/requests/ingest", response_model=NormalizedRequest)
async def ingest_request(payload: IngestRequestInput, x_actor_email: str | None = Header(default=None)) -> NormalizedRequest:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "create_task")
    payload = payload.model_copy(update={"sender": payload.sender or actor.email})
    service = get_request_service()
    return service.ingest(payload)


@app.get("/requests/{request_id}", response_model=NormalizedRequest)
async def get_request(request_id: str, x_actor_email: str | None = Header(default=None)) -> NormalizedRequest:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "create_task")
    repository = get_request_repository()
    item = repository.get(request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Request not found.")
    return item


@app.get("/projects")
async def get_projects(x_actor_email: str | None = Header(default=None)) -> list[dict]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_non_archived_projects")
    client = get_youtrack_client()
    try:
        projects = await client.list_projects()
        if actor.user_type == UserType.team:
            projects = [item for item in projects if not item.get("archived")]
        return projects
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/search",
    summary="Search projects by hint",
    description="Search YouTrack projects by customer hint, project name, or short name. Non-archived projects are ranked first.",
    response_model=list[ProjectSearchResult],
)
async def search_projects(
    q: str,
    include_archived: bool = False,
    limit: int = 10,
    x_actor_email: str | None = Header(default=None),
) -> list[ProjectSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_non_archived_projects")
    service = get_query_service()
    try:
        if actor.user_type == UserType.team:
            include_archived = False
        return await service.search_projects(q, include_archived=include_archived, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/issues/{issue_id}",
    summary="Get issue details",
    description="Read an existing YouTrack issue by issue ID or readable ID such as ES-40.",
)
async def get_issue(issue_id: str, x_actor_email: str | None = Header(default=None)) -> dict:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "advanced_reads")
    client = get_youtrack_client()
    try:
        return await client.get_issue(issue_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/issues/{issue_id}/edit",
    summary="Edit an existing issue",
    description="Update summary and/or description of an existing YouTrack issue. Use this when the user wants to rename or rewrite an issue that already exists.",
)
async def edit_issue(issue_id: str, payload: IssueEditInput, x_actor_email: str | None = Header(default=None)) -> dict:
    actor = _resolve_actor(x_actor_email)
    if actor.user_type == UserType.visitor:
        _assert_issue_edit_allowed(actor, issue_id)
    else:
        _assert_capability(actor, "assist_mail")
    if payload.summary is None and payload.description is None:
        raise HTTPException(status_code=400, detail="At least one of summary or description must be provided.")
    client = get_youtrack_client()
    try:
        response = await client.update_issue(
            issue_id,
            {key: value for key, value in payload.model_dump().items() if value is not None},
        )
        return {
            **response,
            "url": client.issue_url(response.get("idReadable") or response.get("id") or issue_id),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/issues/{issue_id}/work-items",
    summary="List work items of an issue",
    description="Read existing work items attached to a YouTrack issue. Use this before editing a worklog when the work item ID is unknown.",
)
async def list_issue_work_items(issue_id: str, x_actor_email: str | None = Header(default=None)) -> list[dict]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "advanced_reads")
    client = get_youtrack_client()
    try:
        return await client.list_issue_work_items(issue_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/issues/{issue_id}/work-items",
    summary="Create a new work item",
    description="Create a new worklog entry directly on an existing issue.",
)
async def create_issue_work_item(issue_id: str, payload: WorkItemCreateInput, x_actor_email: str | None = Header(default=None)) -> dict:
    actor = _resolve_actor(x_actor_email)
    if actor.user_type == UserType.visitor:
        _assert_issue_edit_allowed(actor, issue_id)
    else:
        _assert_capability(actor, "assist_mail")
    client = get_youtrack_client()
    try:
        response = await client.add_work_item(
            issue_id,
            {
                "text": payload.text,
                "date": int(payload.work_date.strftime("%s")) * 1000,
                "duration": {"minutes": payload.duration_minutes},
            },
        )
        return {
            **response,
            "issue_id": issue_id,
            "issue_url": client.issue_url(issue_id),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/issues/{issue_id}/work-items/{item_id}/edit",
    summary="Edit an existing work item",
    description="Update text, duration, and/or date of an existing YouTrack work item. Use this when the user wants to correct a previously created worklog.",
)
async def edit_issue_work_item(issue_id: str, item_id: str, payload: WorkItemEditInput, x_actor_email: str | None = Header(default=None)) -> dict:
    actor = _resolve_actor(x_actor_email)
    if actor.user_type == UserType.visitor:
        _assert_issue_edit_allowed(actor, issue_id)
    else:
        _assert_capability(actor, "assist_mail")
    if payload.text is None and payload.duration_minutes is None and payload.work_date is None:
        raise HTTPException(
            status_code=400,
            detail="At least one of text, duration_minutes, or work_date must be provided.",
        )
    client = get_youtrack_client()
    raw_payload = payload.model_dump()
    request_payload = {}
    if raw_payload["text"] is not None:
        request_payload["text"] = raw_payload["text"]
    if raw_payload["duration_minutes"] is not None:
        request_payload["duration"] = {"minutes": raw_payload["duration_minutes"]}
    if raw_payload["work_date"] is not None:
        request_payload["date"] = int(raw_payload["work_date"].strftime("%s")) * 1000
    try:
        response = await client.update_work_item(issue_id, item_id, request_payload)
        return {
            **response,
            "issue_id": issue_id,
            "issue_url": client.issue_url(issue_id),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/{project_id}/issues",
    summary="List project issues",
    description="List issues in a project with optional query, open-only filter, assignee filter, and updated-since filter.",
    response_model=list[IssueSearchResult],
)
async def list_project_issues(
    project_id: str,
    query: str | None = None,
    only_open: bool = False,
    assignee: str | None = None,
    updated_since: date | None = None,
    limit: int = 20,
    x_actor_email: str | None = Header(default=None),
) -> list[IssueSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_open_tasks")
    service = get_query_service()
    try:
        if actor.user_type == UserType.team:
            only_open = True
        return await service.list_project_issues(
            project_id,
            query=query,
            only_open=only_open,
            assignee=assignee,
            updated_since=updated_since,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/issues/search",
    summary="Search issues",
    description="Search issues across YouTrack or within a specific project. Use this to find the best issue candidate before writing or reporting.",
    response_model=list[IssueSearchResult],
)
async def search_issues(
    q: str,
    project_id: str | None = None,
    only_open: bool = False,
    assignee: str | None = None,
    updated_since: date | None = None,
    limit: int = 20,
    x_actor_email: str | None = Header(default=None),
) -> list[IssueSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_open_tasks")
    service = get_query_service()
    try:
        if actor.user_type == UserType.team:
            only_open = True
        return await service.search_issues(
            q,
            project_id=project_id,
            only_open=only_open,
            assignee=assignee,
            updated_since=updated_since,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/{project_id}/time-tracking/summary",
    summary="Summarize time tracking for a project",
    description="Return total tracked time for a project in a date range, with issue and author breakdowns.",
    response_model=TimeTrackingSummary,
)
async def summarize_project_time(
    project_id: str,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    x_actor_email: str | None = Header(default=None),
) -> TimeTrackingSummary:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "time_reports")
    service = get_query_service()
    try:
        return await service.summarize_project_time(project_id, from_date, to_date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/{project_id}/time-tracking/by-issue",
    summary="Project time tracking by issue",
    description="Return the same project time summary focused on issue breakdown ordering.",
    response_model=TimeTrackingSummary,
)
async def summarize_project_time_by_issue(
    project_id: str,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    x_actor_email: str | None = Header(default=None),
) -> TimeTrackingSummary:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "time_reports")
    service = get_query_service()
    try:
        return await service.summarize_project_time(project_id, from_date, to_date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/{project_id}/articles",
    summary="List project knowledge articles",
    description="List knowledge base articles for a project, optionally filtered by query.",
    response_model=list[ArticleSearchResult],
)
async def list_project_articles(project_id: str, query: str | None = None, limit: int = 20, x_actor_email: str | None = Header(default=None)) -> list[ArticleSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "knowledge_read")
    service = get_query_service()
    try:
        return await service.list_project_articles(project_id, query=query, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/articles/search",
    summary="Search knowledge articles",
    description="Search YouTrack knowledge base articles globally or inside a single project.",
    response_model=list[ArticleSearchResult],
)
async def search_articles(q: str, project_id: str | None = None, limit: int = 20, x_actor_email: str | None = Header(default=None)) -> list[ArticleSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "knowledge_read")
    service = get_query_service()
    try:
        return await service.search_articles(q, project_id=project_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/assistant/project-context",
    summary="Build project context from a hint",
    description="Find the best project match from a natural hint, then return open issues and recent articles for context.",
    response_model=AssistantProjectContext | None,
)
async def assistant_project_context(hint: str, limit: int = 10, x_actor_email: str | None = Header(default=None)) -> AssistantProjectContext | None:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_open_tasks")
    service = get_query_service()
    try:
        return await service.build_project_context(hint, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/assistant/open-work",
    summary="Summarize open work from a project hint",
    description="Resolve a project from a natural hint and return open issues for that project.",
    response_model=list[IssueSearchResult],
)
async def assistant_open_work(project_hint: str, limit: int = 10, x_actor_email: str | None = Header(default=None)) -> list[IssueSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_open_tasks")
    service = get_query_service()
    try:
        context = await service.build_project_context(project_hint, limit=limit)
        return context.open_issues if context else []
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/assistant/time-report",
    summary="Build a time report from a project hint",
    description="Resolve a project from a natural hint and return tracked time totals in the requested date range.",
    response_model=TimeTrackingSummary,
)
async def assistant_time_report(
    project_hint: str,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    x_actor_email: str | None = Header(default=None),
) -> TimeTrackingSummary:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "time_reports")
    service = get_query_service()
    try:
        projects = await service.search_projects(project_hint, include_archived=False, limit=1)
        if not projects:
            raise HTTPException(status_code=404, detail=f"No project found for hint '{project_hint}'.")
        return await service.summarize_project_time(projects[0].project_id, from_date, to_date)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/assistant/time-report/global",
    summary="Build a cross-project time report",
    description="Return total tracked time in the requested date range, grouped by project and optionally filtered by author/login hint.",
    response_model=GlobalTimeTrackingSummary,
)
async def assistant_global_time_report(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    author_hint: str | None = None,
    x_actor_email: str | None = Header(default=None),
) -> GlobalTimeTrackingSummary:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "time_reports")
    service = get_query_service()
    try:
        return await service.summarize_time_report(from_date, to_date, author_hint=author_hint)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/mail/poll/run",
    summary="Run one mail polling cycle",
    description="Fetch unseen emails, filter allowed sender domains, call the configured Open WebUI model, and send email replies for processed messages.",
    response_model=list[MailProcessingRecord],
)
async def run_mail_polling_cycle() -> list[MailProcessingRecord]:
    service = get_mail_automation_service()
    try:
        return await service.run_once()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/actions/preview")
async def preview_actions(payload: PreviewInput, x_actor_email: str | None = Header(default=None)):
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "create_task")
    service = get_preview_service()
    try:
        return service.build_preview(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/actions/commit", response_model=CommitResult)
async def commit_actions(payload: CommitInput, x_actor_email: str | None = Header(default=None)) -> CommitResult:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "create_task")
    service = get_commit_service()
    try:
        result = await service.commit(payload)
        subscription_service = get_issue_subscription_service()
        for issue in result.issue_results:
            if issue.status != "success":
                continue
            issue_ref = issue.remote_id or issue.payload.get("idReadable") or issue.payload.get("id")
            if issue_ref:
                await subscription_service.subscribe(issue_ref, actor.email, requester_name=actor.full_name)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
