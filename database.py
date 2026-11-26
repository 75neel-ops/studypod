from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import bcrypt
import streamlit as st
from gridfs import GridFSBucket
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@st.cache_resource(show_spinner=False)
def mongo_resources():
    cfg = st.secrets.get("mongodb", {})
    uri = cfg.get("uri", "")
    if not uri:
        raise RuntimeError("MongoDB is not configured. Add [mongodb].uri in Streamlit Secrets.")
    db_name = cfg.get("database", "studypod")
    client = MongoClient(uri, serverSelectionTimeoutMS=12000, connectTimeoutMS=12000)
    client.admin.command("ping")
    database = client[db_name]
    database.users.create_index([("username", ASCENDING)], unique=True)
    database.pods.create_index([("invite_code", ASCENDING)], unique=True)
    database.members.create_index([("pod_id", ASCENDING), ("username", ASCENDING)], unique=True)
    database.milestones.create_index([("pod_id", ASCENDING), ("week_number", ASCENDING)], unique=True)
    database.proofs.create_index([("milestone_id", ASCENDING), ("username", ASCENDING)], unique=True)
    database.confidence.create_index(
        [("milestone_id", ASCENDING), ("username", ASCENDING), ("chapter", ASCENDING)], unique=True
    )
    database.learner_plans.create_index([("pod_id", ASCENDING), ("username", ASCENDING)], unique=True)
    database.task_progress.create_index([("pod_id", ASCENDING), ("username", ASCENDING), ("date", ASCENDING)], unique=True)
    return client, database, GridFSBucket(database, bucket_name="studypod_uploads")


def get_db():
    return mongo_resources()[1]


def get_bucket():
    return mongo_resources()[2]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_user(username: str, display_name: str, password: str) -> None:
    db = get_db()
    db.users.insert_one({
        "username": username.lower().strip(),
        "display_name": display_name.strip()[:60],
        "password_hash": hash_password(password),
        "created_at": utcnow(),
    })


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    user = get_db().users.find_one({"username": username.lower().strip()})
    if user and check_password(password, user.get("password_hash", "")):
        return {"username": user["username"], "display_name": user["display_name"]}
    return None


def store_upload(uploaded_file, username: str, purpose: str) -> str | None:
    if uploaded_file is None:
        return None
    raw = uploaded_file.getvalue()
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("Please keep each upload under 5 MB.")
    bucket = get_bucket()
    file_id = bucket.upload_from_stream(
        uploaded_file.name,
        raw,
        metadata={
            "content_type": uploaded_file.type or "application/octet-stream",
            "username": username,
            "purpose": purpose,
            "uploaded_at": utcnow(),
        },
    )
    return str(file_id)


def read_upload(file_id: str) -> tuple[bytes, dict[str, Any]]:
    from bson import ObjectId
    stream = get_bucket().open_download_stream(ObjectId(file_id))
    return stream.read(), stream.metadata or {}


def create_pod_document(pod: dict[str, Any]) -> str:
    result = get_db().pods.insert_one(pod)
    return str(result.inserted_id)


def delete_pod(pod_id, owner_username: str) -> bool:
    """Delete a pod and all dependent records. Only the recorded owner may do this."""
    database = get_db()
    pod = database.pods.find_one({"_id": pod_id, "owner_username": owner_username})
    if not pod:
        return False

    milestones = list(database.milestones.find({"pod_id": pod_id}, {"_id": 1}))
    milestone_ids = [item["_id"] for item in milestones]
    proofs = list(database.proofs.find({"milestone_id": {"$in": milestone_ids}}, {"file_id": 1}))

    upload_ids = set()
    if pod.get("syllabus_file_id"):
        upload_ids.add(str(pod["syllabus_file_id"]))
    for proof in proofs:
        if proof.get("file_id"):
            upload_ids.add(str(proof["file_id"]))

    if milestone_ids:
        database.proofs.delete_many({"milestone_id": {"$in": milestone_ids}})
        database.confidence.delete_many({"milestone_id": {"$in": milestone_ids}})
    database.milestones.delete_many({"pod_id": pod_id})
    database.learner_plans.delete_many({"pod_id": pod_id})
    database.task_progress.delete_many({"pod_id": pod_id})
    database.members.delete_many({"pod_id": pod_id})
    database.pods.delete_one({"_id": pod_id, "owner_username": owner_username})

    # Remove files uploaded specifically for this pod (syllabus and proof attachments).
    from bson import ObjectId
    bucket = get_bucket()
    for file_id in upload_ids:
        try:
            bucket.delete(ObjectId(file_id))
        except Exception:
            # The pod is already deleted; a missing attachment should not block cleanup.
            pass
    return True


def add_member(pod_id, username: str, display_name: str, role: str = "member") -> None:
    get_db().members.insert_one({
        "pod_id": pod_id,
        "username": username,
        "display_name": display_name,
        "role": role,
        "joined_at": utcnow(),
    })


def get_pod_by_code(code: str):
    return get_db().pods.find_one({"invite_code": code.strip().upper()})


def get_user_pods(username: str) -> list[dict[str, Any]]:
    db = get_db()
    memberships = list(db.members.find({"username": username}))
    pod_ids = [m["pod_id"] for m in memberships]
    return list(db.pods.find({"_id": {"$in": pod_ids}}).sort("created_at", -1))


def get_members(pod_id) -> list[dict[str, Any]]:
    return list(get_db().members.find({"pod_id": pod_id}).sort("joined_at", 1))


def get_milestones(pod_id) -> list[dict[str, Any]]:
    return list(get_db().milestones.find({"pod_id": pod_id}).sort("week_number", 1))


def get_milestone(milestone_id: str):
    from bson import ObjectId
    return get_db().milestones.find_one({"_id": ObjectId(milestone_id)})


def submit_proof(milestone_id, username: str, proof: dict[str, Any]) -> None:
    get_db().proofs.update_one(
        {"milestone_id": milestone_id, "username": username},
        {"$set": {**proof, "submitted_at": utcnow()}},
        upsert=True,
    )


def has_proof(milestone_id, username: str) -> bool:
    return get_db().proofs.find_one({"milestone_id": milestone_id, "username": username}) is not None


def save_confidence(milestone_id, username: str, chapter: str, score: int) -> None:
    get_db().confidence.update_one(
        {"milestone_id": milestone_id, "username": username, "chapter": chapter},
        {"$set": {"score": int(score), "updated_at": utcnow()}},
        upsert=True,
    )


def get_confidence(milestone_id) -> list[dict[str, Any]]:
    return list(get_db().confidence.find({"milestone_id": milestone_id}))


def save_vault_notes(milestone_id, notes: str) -> None:
    get_db().milestones.update_one(
        {"_id": milestone_id},
        {"$set": {"vault_notes": notes[:12000], "updated_at": utcnow()}},
    )


def get_proof(milestone_id, username: str):
    return get_db().proofs.find_one({"milestone_id": milestone_id, "username": username})


def create_milestones(pod_id, plan: list[dict[str, Any]]) -> None:
    db = get_db()
    for week in plan:
        db.milestones.update_one(
            {"pod_id": pod_id, "week_number": week["week_number"]},
            {"$setOnInsert": {
                "pod_id": pod_id,
                **week,
                "vault_notes": "",
                "created_at": utcnow(),
            }},
            upsert=True,
        )



def get_learner_plan(pod_id, username: str) -> dict[str, Any] | None:
    return get_db().learner_plans.find_one({"pod_id": pod_id, "username": username})


def save_learner_plan(pod_id, username: str, schedule: list[dict[str, Any]]) -> None:
    get_db().learner_plans.update_one(
        {"pod_id": pod_id, "username": username},
        {"$set": {"schedule": schedule, "updated_at": utcnow()},
         "$setOnInsert": {"pod_id": pod_id, "username": username, "created_at": utcnow()}},
        upsert=True,
    )


def get_task_progress(pod_id, username: str) -> list[dict[str, Any]]:
    return list(get_db().task_progress.find(
        {"pod_id": pod_id, "username": username}
    ).sort("date", 1))


def save_task_progress(pod_id, username: str, task_date: str,
                       status: str, hours_spent: float, note: str = "") -> None:
    get_db().task_progress.update_one(
        {"pod_id": pod_id, "username": username, "date": task_date},
        {"$set": {
            "status": status,
            "hours_spent": max(0.0, min(24.0, float(hours_spent))),
            "note": note[:500],
            "updated_at": utcnow(),
        }, "$setOnInsert": {"pod_id": pod_id, "username": username, "date": task_date}},
        upsert=True,
    )

def member_count(pod_id) -> int:
    return get_db().members.count_documents({"pod_id": pod_id})


def is_member(pod_id, username: str) -> bool:
    return get_db().members.find_one({"pod_id": pod_id, "username": username}) is not None


def verify_user_pod(username: str, pod_id) -> bool:
    return is_member(pod_id, username)
