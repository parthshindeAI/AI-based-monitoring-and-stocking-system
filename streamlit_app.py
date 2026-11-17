import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from ui.dashboard import render_dashboard


def _render_authentication_gate() -> None:
    try:
        secrets = st.secrets
        configured = bool(secrets)
    except StreamlitSecretNotFoundError:
        secrets = {}
        configured = False

    if not configured or "auth" not in secrets:
        st.sidebar.warning("Sign-in is not configured. Local development mode is active.")
        return

    auth_config = secrets["auth"]
    required_keys = {"redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url"}
    missing_keys = required_keys.difference(auth_config)
    if missing_keys:
        st.error(f"Sign-in configuration is incomplete. Missing: {', '.join(sorted(missing_keys))}.")
        st.stop()

    allowed_emails = secrets.get("access", {}).get("allowed_emails", [])
    if not allowed_emails:
        st.error("Sign-in is configured, but no access allow-list is set. Add [access].allowed_emails to secrets.toml.")
        st.stop()

    if not st.user.is_logged_in:
        st.title("Sign in required")
        st.button("Sign in with your organization", on_click=st.login)
        st.stop()

    user_email = str(st.user.get("email", "")).strip().casefold()
    permitted_emails = {str(email).strip().casefold() for email in allowed_emails}
    if not user_email or user_email not in permitted_emails:
        st.error("Your account is not authorized to access this inventory app.")
        st.button("Sign out", on_click=st.logout)
        st.stop()

    st.sidebar.caption(f"Signed in as {user_email}")
    st.sidebar.button("Sign out", on_click=st.logout)


def main() -> None:
    _render_authentication_gate()
    render_dashboard()


if __name__ == "__main__":
    main()
