import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import photo_storage
from app.services.photo_storage import PhotoStorageError

client = TestClient(app)

# Correct magic bytes, junk behind them: enough for a detector that only
# reads the header, which is exactly what the API promises to do.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 128
WEBP = b"RIFF" + (100).to_bytes(4, "little") + b"WEBP" + b"\x00" * 128


class FakeCloudinary:
    """The provider at its best: uploads stick, fetches echo, deletes go."""

    def __init__(self):
        self.assets = {}
        self.deleted = []
        self.counter = 0

    def upload(self, vehicle_id, content, extension):
        self.counter += 1
        public_id = f"vehicles/{vehicle_id}/asset{self.counter}"
        url = (
            "https://res.cloudinary.com/demo/image/upload/"
            f"v1/{public_id}.{extension}"
        )
        self.assets[public_id] = bytes(content)
        return public_id, url

    def fetch(self, url):
        for public_id, content in self.assets.items():
            if public_id in url:
                return content
        raise PhotoStorageError("no such asset")

    def destroy(self, public_id):
        self.assets.pop(public_id, None)
        self.deleted.append(public_id)


@pytest.fixture(autouse=True)
def fake_photos(monkeypatch):
    """The API never talks to a real CDN in tests - same seam as Brevo."""
    fake = FakeCloudinary()
    monkeypatch.setattr(photo_storage, "upload_photo", fake.upload)
    monkeypatch.setattr(photo_storage, "fetch_photo", fake.fetch)
    monkeypatch.setattr(photo_storage, "delete_photo", fake.destroy)
    return fake


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


def test_upload_serve_and_flag_the_photo(accounts, fake_photos):
    accounts.register(client, "Photo Owner", "photo-owner@example.com")
    token = accounts.login(client, "photo-owner@example.com")
    vehicle_id = create_vehicle(token)

    before = client.get(f"/vehicles/{vehicle_id}", headers=auth(token))
    assert before.json()["has_photo"] is False

    response = upload(vehicle_id, token)
    assert response.status_code == 201, response.text
    assert len(fake_photos.assets) == 1

    after = client.get(f"/vehicles/{vehicle_id}", headers=auth(token))
    assert after.json()["has_photo"] is True

    served = client.get(f"/vehicles/{vehicle_id}/photo", headers=auth(token))
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    # private: no shared cache keeps somebody's car photo around.
    assert served.headers["cache-control"] == "private, max-age=3600"
    assert served.content == PNG


def test_replacing_keeps_exactly_one_asset(accounts, fake_photos):
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

    # The old asset is destroyed, never left dangling on the provider.
    assert len(fake_photos.assets) == 1
    assert len(fake_photos.deleted) == 1

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


def test_delete_photo_removes_row_and_asset(accounts, fake_photos):
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
    assert fake_photos.assets == {}
    assert len(fake_photos.deleted) == 1


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

    # And none of those attempts touched the asset.
    kept = client.get(f"/vehicles/{vehicle_id}/photo", headers=auth(token_a))
    assert kept.status_code == 200
    assert kept.content == PNG


def test_oversized_photo_is_refused(accounts, fake_photos):
    accounts.register(client, "Big Photo", "big-photo@example.com")
    token = accounts.login(client, "big-photo@example.com")
    vehicle_id = create_vehicle(token)

    huge = PNG + b"a" * (5 * 1024 * 1024)
    response = upload(vehicle_id, token, content=huge)

    assert response.status_code == 413
    assert response.json()["detail"] == "Photo exceeds the 5 MB limit"
    # Rejected before the provider ever hears about it.
    assert fake_photos.assets == {}


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
    accounts, db, fake_photos
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
    assert fake_photos.assets == {}


def test_deleting_the_vehicle_takes_its_asset_with_it(
    accounts, fake_photos
):
    accounts.register(client, "Scrapyard", "scrapyard@example.com")
    token = accounts.login(client, "scrapyard@example.com")
    vehicle_id = create_vehicle(token)
    upload(vehicle_id, token)
    assert len(fake_photos.assets) == 1

    response = client.delete(f"/vehicles/{vehicle_id}", headers=auth(token))
    assert response.status_code == 200

    # No orphan on the provider: the row is gone and the asset followed.
    assert fake_photos.assets == {}
    assert len(fake_photos.deleted) == 1


def test_a_failed_upload_leaves_the_database_unaware(
    accounts, db, monkeypatch
):
    accounts.register(client, "Cdn Down", "cdn-down@example.com")
    token = accounts.login(client, "cdn-down@example.com")
    vehicle_id = create_vehicle(token)

    def broken_upload(**kwargs):
        raise PhotoStorageError("provider is down")

    monkeypatch.setattr(photo_storage, "upload_photo", broken_upload)

    response = upload(vehicle_id, token)

    assert response.status_code == 503
    assert response.json()["detail"] == "Photo storage unavailable"

    from app.models.vehicle import Vehicle

    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    db.refresh(vehicle)
    assert vehicle.photo_public_id is None
    assert vehicle.photo_url is None


def test_a_failed_fetch_answers_503(accounts, monkeypatch):
    accounts.register(client, "Cdn Read Down", "cdn-read@example.com")
    token = accounts.login(client, "cdn-read@example.com")
    vehicle_id = create_vehicle(token)
    assert upload(vehicle_id, token).status_code == 201

    def broken_fetch(url):
        raise PhotoStorageError("provider is down")

    monkeypatch.setattr(photo_storage, "fetch_photo", broken_fetch)

    response = client.get(
        f"/vehicles/{vehicle_id}/photo", headers=auth(token)
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Photo storage unavailable"
