from __future__ import annotations

import html
from datetime import datetime

from app.config import settings
from app.models import PanelStatus, UserType, WhitelistedUser


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


def render_login_page(error_message: str | None = None) -> str:
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


def render_panel(
    status_model: PanelStatus,
    users: list[WhitelistedUser],
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
