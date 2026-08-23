import logging
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Photo, Species

logger = logging.getLogger(__name__)


def refresh_species_for_photo(
    session: Session,
    scientific_name: str,
    manager_factory: Optional[Callable] = None,
) -> None:
    """Recalculate species stats after a photo is added/removed/corrected.

    Updates the SQLAlchemy ``species`` table (create/update/delete the row based
    on the remaining photo count) and, when *manager_factory* is provided,
    refreshes the legacy sqlite3 species_stats tree via the returned manager.
    """
    if not scientific_name:
        return

    stats = session.query(
        func.count(Photo.id).label("count"),
    ).filter(Photo.scientific_name == scientific_name).first()

    species = session.query(Species).filter(Species.scientific_name == scientific_name).first()

    if stats.count == 0:
        if species:
            session.delete(species)
    else:
        if not species:
            bird_info = None
            if manager_factory is not None:
                manager = manager_factory()
                try:
                    bird_info = manager.get_bird_info(scientific_name)
                finally:
                    manager.close()
            species = Species(
                scientific_name=scientific_name,
                chinese_name=bird_info.get("chinese_name") if bird_info else "",
                family_cn=bird_info.get("family_cn") if bird_info else "",
                family_sci=bird_info.get("family_sci") if bird_info else "",
                photo_count=0,
            )
            session.add(species)
        species.photo_count = stats.count

    session.commit()

    if manager_factory is not None:
        manager = manager_factory()
        try:
            manager.update_species_stats_for_photo(scientific_name)
        finally:
            manager.close()
