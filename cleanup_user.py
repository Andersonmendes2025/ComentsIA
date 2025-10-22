from main import app
from models import (
    ReservationIndex,  # , User  # se quiser apagar user também
    Review,
    UploadLog,
    db,
)

USER_ID = "andersonmendes575@gmail.com"  # ex.: "anderson@gmail.com"


def count_all(uid):
    ri = (
        db.session.query(ReservationIndex)
        .filter_by(user_id=uid, source="booking")
        .count()
    )
    ul = db.session.query(UploadLog).filter_by(user_id=uid, source="booking").count()
    rv = db.session.query(Review).filter_by(user_id=uid, source="booking").count()
    return ri, ul, rv


with app.app_context():
    before = count_all(USER_ID)
    print(
        "Antes:",
        {"ReservationIndex": before[0], "UploadLog": before[1], "Review": before[2]},
    )

    db.session.query(ReservationIndex).filter_by(
        user_id=USER_ID, source="booking"
    ).delete(synchronize_session=False)
    db.session.query(UploadLog).filter_by(user_id=USER_ID, source="booking").delete(
        synchronize_session=False
    )
    db.session.query(Review).filter_by(user_id=USER_ID, source="booking").delete(
        synchronize_session=False
    )
    # (opcional) apagar o próprio usuário antigo:
    # from models import User
    # db.session.query(User).filter_by(id=USER_ID).delete(synchronize_session=False)

    db.session.commit()

    after = count_all(USER_ID)
    print(
        "Depois:",
        {"ReservationIndex": after[0], "UploadLog": after[1], "Review": after[2]},
    )
