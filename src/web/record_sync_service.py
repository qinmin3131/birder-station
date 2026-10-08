def serialize_draft(draft):
    return {
        "id": draft.id, "status": draft.status, "remote_id": draft.report.remote_id,
        "outing_id": draft.outing_id, "location_name": draft.location_name,
        "duplicate_warning": bool(draft.duplicate_warning),
        "latitude": getattr(draft, "latitude", None),
        "longitude": getattr(draft, "longitude", None),
        "protocol": getattr(draft, "protocol", None),
        "start_time": getattr(draft, "start_time", None),
        "duration_minutes": getattr(draft, "duration_minutes", None),
        "distance_km": getattr(draft, "distance_km", None),
        "observer_count": getattr(draft, "observer_count", None),
        "is_complete_checklist": getattr(draft, "is_complete_checklist", None),
        "suggestion": getattr(draft, "suggestion_json", None) or {},
        "items": [{
            "id": item.id, "source": item.source, "birdreport_name": item.birdreport_name,
            "local_name": item.local_name, "scientific_name": item.scientific_name,
            "ebird_name": item.ebird_name, "count_value": item.count_value,
            "included": item.included, "mapping_status": item.mapping_status,
        } for item in draft.items],
    }


def serialize_export(result):
    return {
        "batch_id": result.batch_id,
        "download_url": f"/api/ebird/exports/{result.batch_id}",
        "import_url": "https://ebird.org/import/upload.form",
        "duplicate_of_batch_id": result.duplicate_of_batch_id,
    }
