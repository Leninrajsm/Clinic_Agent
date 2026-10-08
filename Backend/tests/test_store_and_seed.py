from app.db.seed import DayFill, Leave, SeedOverrides, seed_sandbox
from app.repo.clinic_repo import ClinicRepository
from app.repo.store import MemoryStore


async def test_memory_store_operators_and_conditional_update():
    s = MemoryStore()
    await s.insert_many("c", [{"id": 1, "n": 5, "st": "open"}, {"id": 2, "n": 9, "st": "open"}])
    assert [d["id"] for d in await s.find("c", {"n": {"$gte": 6}})] == [2]
    assert await s.update_one("c", {"id": 1, "st": "open"}, {"st": "held"})
    assert not await s.update_one("c", {"id": 1, "st": "open"}, {"st": "held"})  # second hold fails
    assert [d["id"] for d in await s.find("c", {}, sort=[("n", -1)])] == [2, 1]


async def test_seed_overrides(clock):
    repo = ClinicRepository(MemoryStore())
    summary = await seed_sandbox(repo, "x", clock, SeedOverrides(
        prefill_percent=0,
        fill_days=[DayFill(date="2026-10-16", specialty="cardiology")],
        provider_leave=[Leave(provider_id="prov_shah", date_from="2026-10-12", date_to="2026-11-01")],
    ))
    assert summary["patients"] == 9
    start, end = clock.at(clock.today().replace(day=16), 0), clock.at(clock.today().replace(day=17), 0)
    assert await repo.open_slots("x", start, end, specialty="cardiology") == []
    assert await repo.open_slots("x", clock.now(), clock.at(clock.today().replace(day=31), 0),
                                 provider_id="prov_shah") == []


async def test_find_patient_requires_exact_name_and_dob(repo):
    assert (await repo.find_patient("test", "  maria   LOPEZ ", "1988-03-14")).id == "pt_maria"
    assert await repo.find_patient("test", "Maria Lopez", "1988-03-15") is None
    # Two John Smiths: DOB disambiguates
    assert (await repo.find_patient("test", "John Smith", "1985-09-30")).id == "pt_john_b"
