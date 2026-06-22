from flask import Blueprint, jsonify

from database import db_session
from models import Package
from serializers import package_dict

bp = Blueprint("packages", __name__, url_prefix="/api")


@bp.get("/packages")
def list_packages():
    packages = db_session.query(Package).order_by(Package.price.asc(), Package.id.asc()).all()
    return jsonify([package_dict(p) for p in packages])
