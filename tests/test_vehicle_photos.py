import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)

# Correct magic bytes, junk behind them: enough for a detector that only
# reads the header, which is exactly what the API promises to do.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 128
WEBP = b"RIFF" + (100).to_bytes(4, "little") + b"WEBP" + b"\x00" * 128


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    """Every test writes its photos into its own throwaway directory."""
    monkeypatch.setattr(settings, "uploads_dir", str(tmp_path))
    return tmp_path


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_vehicle(token, vin="TESTPHOTO00000001"):
    response = client.post(
        "/vehicles/",
        headers=auth(token),
        json={
            "make": "Ford",
            "model": "Fiesta",
            "year": 2020,
            "vin": vin,
            "mileage": 1000,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(vehicle_id, token, content=PNG, filename="photo.png",
           content_type="image/png"):
    return client.post(
        f"/vehicles/{vehicle_id}/photo",
        headers=auth(token),
        files={"file": (filename, content, content_type)},
    )


def test_upload_serve_and_flag_the_photo(accounts, isolated_uploads):
    accounts.register(client, "Photo Owner", "photo-owner@example.com")
    token = accounts.login(client, "photo-owner@example.com")
    vehicle_id = create_vehicle(token)

    before = client.get(f"/vehicles/{vehicle_id}", headers=auth(token))
    assert before.json()["has_photo"] is False

    response = upload(vehicle_id, token)
    assert response.status_code == 201, response.text

    after = client.get(f"/vehicles/{vehicle_id}", headers=auth(token))
    assert after.json()["has_photo"] is True

    served = client.get(f"/vehicles/{vehicle_id}/photo", headers=auth(token))
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    # private: no shared cache may keep somebody's car photo around.
    assert served.headers["cache-control"] == "private, max-age=3600"
    assert served.content == PNG

    assert len(list(isolated_uploads.iterdir())) == 1


def test_replacing_keeps_exactly_one_file(accounts, isolated_uploads):
    accounts.register(client, "Replace Owner", "replace@example.com")
    token = accounts.login(client, "replace@example.com")
    vehicle_id = create_vehicle(token)

    assert upload(vehicle_id, token).status_code == 201
    replaced = upload(
        vehicle_id, token, content=JPEG, filename="photo.jpg",
        content_type="image/jpeg",
    )
    # A replacement is not a creation: 200, same vehicle, same route.
    assert replaced.status_code == 200, replaced.text

    assert len(list(isolated_uploads.iterdir())) == 1

    served = client.get(f"/vehicles/{vehicle_id}/photo", headers=auth(token))
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"
    assert served.content == JPEG


def test_webp_is_accepted(accounts):
    accounts.register(client, "Webp Owner", "webp@example.com")
    token = accounts.login(client, "webp@example.com")
    vehicle_id = create_vehicle(token)

    response = upload(
        vehicle_id, token, content=WEBP, filename="photo.webp",
        content_type="image/webp",
    )
    assert response.status_code == 201, response.text

    served = client.get(f"/vehicles/{vehicle_id}/photo", headers=auth(token))
    assert served.headers["content-type"] == "image/webp"


def test_delete_photo_removes_row_and_file(accounts, isolated_uploads):
    accounts.register(client, "Deleter", "photo-deleter@example.com")
    token = accounts.login(client, "photo-deleter@example.com")
    vehicle_id = create_vehicle(token)
    upload(vehicle_id, token)

    response = client.delete(
        f"/vehicles/{vehicle_id}/photo", headers=auth(token)
    )
    assert response.status_code == 204
    assert response.content == b""

    gone = client.get(f"/vehicles/{vehicle_id}/photo", headers=auth(token))
    assert gone.status_code == 404

    vehicle = client.get(f"/vehicles/{vehicle_id}", headers=auth(token))
    assert vehicle.json()["has_photo"] is False
    assert list(isolated_uploads.iterdir()) == []


def test_a_vehicle_without_a_photo_answers_404(accounts):
    accounts.register(client, "No Photo Yet", "no-photo@example.com")
    token = accounts.login(client, "no-photo@example.com")
    vehicle_id = create_vehicle(token)

    response = client.get(
        f"/vehicles/{vehicle_id}/photo", headers=auth(token)
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Vehicle has no photo"


def test_deleting_twice_is_a_404(accounts):
    accounts.register(client, "Double Delete", "double-del@example.com")
    token = accounts.login(client, "double-del@example.com")
    vehicle_id = create_vehicle(token)
    upload(vehicle_id, token)

    first = client.delete(
        f"/vehicles/{vehicle_id}/photo", headers=auth(token)
    )
    second = client.delete(
        f"/vehicles/{vehicle_id}/photo", headers=auth(token)
    )

    assert first.status_code == 204
    assert second.status_code == 404


def test_another_owner_cannot_touch_the_photo(accounts):
    accounts.register(client, "Owner A", "owner-a@example.com")
    accounts.register(client, "Owner B", "owner-b@example.com")
    token_a = accounts.login(client, "owner-a@example.com")
    token_b = accounts.login(client, "owner-b@example.com")
    vehicle_id = create_vehicle(token_a)
    upload(vehicle_id, token_a)

    uploaded = upload(vehicle_id, token_b)
    assert uploaded.status_code == 403
    assert uploaded.json()["detail"] == (
        "Not authorized to upload a photo to this vehicle"
    )

    served = client.get(f"/vehicles/{vehicle_id}/photo", headers=auth(token_b))
    assert served.status_code == 403
    assert served.json()["detail"] == "Not authorized to access this vehicle"

    removed = client.delete(
        f"/vehicles/{vehicle_id}/photo", headers=auth(token_b)
    )
    assert removed.status_code == 403
    assert removed.json()["detail"] == (
        "Not authorized to remove a photo from this vehicle"
    )

    # And none of those attempts touched the file.
    kept = client.get(f"/vehicles/{vehicle_id}/photo", headers=auth(token_a))
    assert kept.status_code == 200
    assert kept.content == PNG


def test_oversized_photo_is_refused(accounts, isolated_uploads):
    accounts.register(client, "Big Photo", "big-photo@example.com")
    token = accounts.login(client, "big-photo@example.com")
    vehicle_id = create_vehicle(token)

    huge = PNG + b"a" * (5 * 1024 * 1024)
    response = upload(vehicle_id, token, content=huge)

    assert response.status_code == 413
    assert response.json()["detail"] == "Photo exceeds the 5 MB limit"
    assert list(isolated_uploads.iterdir()) == []


def test_the_declared_content_type_is_not_trusted(accounts):
    accounts.register(client, "Liar Header", "liar-header@example.com")
    token = accounts.login(client, "liar-header@example.com")
    vehicle_id = create_vehicle(token)

    # Claims image/jpeg on both the filename and the header; the bytes
    # say otherwise, and the bytes are the only thing believed.
    response = upload(
        vehicle_id,
        token,
        content=b"MZ this is not an image at all",
        filename="totally-a-photo.jpg",
        content_type="image/jpeg",
    )

    assert response.status_code == 415
    assert response.json()["detail"] == (
        "Only JPEG, PNG and WEBP images are accepted"
    )


def test_an_empty_file_is_refused(accounts):
    accounts.register(client, "Empty Photo", "empty-photo@example.com")
    token = accounts.login(client, "empty-photo@example.com")
    vehicle_id = create_vehicle(token)

    response = upload(vehicle_id, token, content=b"")

    assert response.status_code == 422
    assert response.json()["detail"] == "The photo file is empty"


def test_an_unknown_vehicle_answers_403_like_the_whole_router(accounts):
    accounts.register(client, "No Such Car", "no-such-car@example.com")
    token = accounts.login(client, "no-such-car@example.com")

    uploaded = upload(999999, token)
    assert uploaded.status_code == 403
    assert uploaded.json()["detail"] == (
        "Not authorized to upload a photo to this vehicle"
    )

    served = client.get("/vehicles/999999/photo", headers=auth(token))
    assert served.status_code == 403
    assert served.json()["detail"] == "Not authorized to access this vehicle"


def test_a_verified_vehicle_photo_is_out_of_the_owners_reach(
    accounts, db, isolated_uploads
):
    accounts.register(client, "Verified Ride", "verified-ride@example.com")
    token = accounts.login(client, "verified-ride@example.com")
    vehicle_id = create_vehicle(token)

    # Same arrangement update_vehicle tests rely on: once a mechanic has
    # verified the vehicle, the owner can no longer modify it.
    from app.models.vehicle import Vehicle

    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    vehicle.verified = True
    db.commit()

    response = upload(vehicle_id, token)

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Customers can only modify unverified vehicles"
    )
    assert list(isolated_uploads.iterdir()) == []


def test_deleting_the_vehicle_takes_its_photo_file_with_it(
    accounts, isolated_uploads
):
    accounts.register(client, "Scrapyard", "scrapyard@example.com")
    token = accounts.login(client, "scrapyard@example.com")
    vehicle_id = create_vehicle(token)
    upload(vehicle_id, token)
    assert len(list(isolated_uploads.iterdir())) == 1

    response = client.delete(f"/vehicles/{vehicle_id}", headers=auth(token))
    assert response.status_code == 200

    # No orphan file: the row is gone and the disk followed it.
    assert list(isolated_uploads.iterdir()) == []
