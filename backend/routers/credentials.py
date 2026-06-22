import logging

from flask import Blueprint, jsonify, g

from database import db_session
from models import Credential, CredStatus
from security import login_required
from serializers import credential_dict
from provisioning import issue_credentials

log = logging.getLogger("iaas.credentials")
bp = Blueprint("credentials", __name__, url_prefix="/api")


@bp.get("/credentials")
@login_required
def list_credentials():
    """List the user's Access Key IDs. The secret is NEVER returned here again."""
    creds = (
        db_session.query(Credential)
        .filter(Credential.user_id == g.current_user.id, Credential.status == CredStatus.active)
        .order_by(Credential.id.desc())
        .all()
    )
    return jsonify([credential_dict(c) for c in creds])


@bp.post("/credentials")
@login_required
def create_credential():
    """Mint a new key pair. The plaintext secret is returned exactly once."""
    try:
        cred, secret = issue_credentials(g.current_user)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        log.error("Credential mint failed for user %s: %s", g.current_user.id, e)
        return jsonify({"detail": "Could not generate credentials"}), 502
    return jsonify(credential_dict(cred, secret=secret)), 201
