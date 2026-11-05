"""Durable job inspection and control endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/stats")
async def job_stats():
    from palimind.jobs import stats

    return await asyncio.to_thread(stats)


@router.get("")
async def list_jobs_endpoint(status: str | None = None, kind: str | None = None, limit: int = 100):
    from palimind.jobs import list_jobs

    return {
        "jobs": await asyncio.to_thread(
            list_jobs, status=status, kind=kind, limit=max(1, min(int(limit or 100), 500))
        )
    }


@router.get("/{job_id}")
async def get_job_endpoint(job_id: str):
    from palimind.jobs import get_job, list_events

    job = await asyncio.to_thread(get_job, job_id)
    if job is None:
        return {"error": "job not found"}
    return {"job": job, "events": await asyncio.to_thread(list_events, job_id)}


@router.post("/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str):
    from palimind.jobs import cancel_job

    job = await asyncio.to_thread(cancel_job, job_id)
    return {"job": job} if job else {"error": "job not found"}


@router.post("/{job_id}/retry")
async def retry_job_endpoint(job_id: str):
    from palimind.jobs import retry_job

    job = await asyncio.to_thread(retry_job, job_id)
    return {"job": job} if job else {"error": "job not found"}


@router.delete("/{job_id}")
async def delete_job_endpoint(job_id: str):
    from palimind.jobs import delete_job

    ok = await asyncio.to_thread(delete_job, job_id)
    return {"status": "success" if ok else "not_found"}
