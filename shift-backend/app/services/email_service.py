"""
Servico de envio de email com backend abstrato (console ou Resend).
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


SCOPE_LABELS = {
    "ORGANIZATION": "organizacao",
    "WORKSPACE": "workspace",
    "PROJECT": "projeto",
}


def _build_invitation_html(
    inviter_name: str,
    scope_label: str,
    scope_name: str,
    role: str,
    accept_url: str,
) -> str:
    return f"""\
<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 0;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="background:#141414;border:1px solid #262626;border-radius:12px;padding:40px;">
        <tr><td>
          <h1 style="margin:0 0 8px;font-size:20px;font-weight:700;color:#fafafa;">Shift</h1>
          <p style="margin:0 0 24px;font-size:14px;color:#a1a1aa;">Voce recebeu um convite</p>
          <p style="margin:0 0 24px;font-size:15px;color:#e4e4e7;line-height:1.6;">
            <strong style="color:#fafafa;">{inviter_name}</strong> convidou voce para o
            {scope_label} <strong style="color:#fafafa;">{scope_name}</strong>
            como <strong style="color:#fafafa;">{role}</strong>.
          </p>
          <table cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
            <tr><td style="background:#fafafa;border-radius:8px;padding:12px 32px;">
              <a href="{accept_url}" style="color:#0a0a0a;text-decoration:none;font-size:14px;font-weight:600;">
                Aceitar Convite
              </a>
            </td></tr>
          </table>
          <p style="margin:0;font-size:12px;color:#71717a;line-height:1.5;">
            Este convite expira em {settings.INVITATION_EXPIRE_DAYS} dias.
            Se voce nao reconhece este convite, ignore este email.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_invitation_text(
    inviter_name: str,
    scope_label: str,
    scope_name: str,
    role: str,
    accept_url: str,
) -> str:
    return (
        f"{inviter_name} convidou voce para o {scope_label} "
        f'"{scope_name}" como {role}.\n\n'
        f"Aceite o convite acessando: {accept_url}\n\n"
        f"Este convite expira em {settings.INVITATION_EXPIRE_DAYS} dias."
    )


class EmailService:
    """Abstração para envio de emails. Backend configurável via EMAIL_BACKEND."""

    async def send_invitation_email(
        self,
        to_email: str,
        inviter_name: str,
        scope_label: str,
        scope_name: str,
        role: str,
        accept_url: str,
    ) -> bool:
        subject = f"{inviter_name} convidou voce para o Shift"
        html = _build_invitation_html(
            inviter_name, scope_label, scope_name, role, accept_url
        )
        text = _build_invitation_text(
            inviter_name, scope_label, scope_name, role, accept_url
        )

        if settings.EMAIL_BACKEND == "resend":
            return await self._send_resend(to_email, subject, html, text)

        return self._send_console(to_email, subject, text, accept_url)

    def _send_console(
        self, to_email: str, subject: str, text: str, accept_url: str
    ) -> bool:
        print(
            "\n╔══════════════════════════════════════╗\n"
            "║        EMAIL (console backend)       ║\n"
            "╚══════════════════════════════════════╝\n"
            f"  Para: {to_email}\n"
            f"  Assunto: {subject}\n"
            "  ──────────────────────────────────\n"
            f"  {text}\n"
            "  ──────────────────────────────────\n"
            f"  Link: {accept_url}\n"
        )
        return True

    async def _send_resend(
        self, to_email: str, subject: str, html: str, text: str
    ) -> bool:
        try:
            import resend

            resend.api_key = settings.RESEND_API_KEY
            resend.Emails.send(
                {
                    "from": settings.EMAIL_FROM,
                    "to": [to_email],
                    "subject": subject,
                    "html": html,
                    "text": text,
                }
            )
            return True
        except Exception:
            logger.exception("Falha ao enviar email via Resend para %s", to_email)
            return False


email_service = EmailService()
