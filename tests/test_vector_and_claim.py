"""Vector index create and query; atomic Task claim under concurrent clients."""

import threading

from falkordb import FalkorDB

from app import config
from app.graph.client import TenantGraph, rows


def test_vector_index_create_and_query(make_graph):
    tg = make_graph()
    tg.write("chunk_vector_index", {"dim": 4})
    tg.write("chunk_upsert", {"rows": [
        {"id": "c1", "text": "close valve V-09", "source": "synthetic", "embedding": [1.0, 0.0, 0.0, 0.0]},
        {"id": "c2", "text": "rack power feed", "source": "synthetic", "embedding": [0.0, 1.0, 0.0, 0.0]},
        {"id": "c3", "text": "valve maintenance", "source": "synthetic", "embedding": [0.9, 0.1, 0.0, 0.0]},
    ]})
    got = rows(tg.read("chunk_search", {"k": 2, "vec": [1.0, 0.0, 0.0, 0.0]}))
    assert [r["id"] for r in got] == ["c1", "c3"]
    # The score is a cosine distance: about 0 for the identical vector, larger for the next one.
    assert got[0]["score"] < 1e-5 < got[1]["score"] < 0.1


def test_claim_race_exactly_one_winner_per_task(make_graph):
    tg = make_graph()
    task_ids = [f"task_{i}" for i in range(20)]
    tg.write("task_create", {"ids": task_ids, "kind": "probe", "source": "synthetic"})

    n_workers = 8
    wins: dict[str, list[str]] = {t: [] for t in task_ids}
    lock = threading.Lock()
    barrier = threading.Barrier(n_workers)

    def worker(name: str):
        # each worker has its own client connection, like separate agent processes
        db = FalkorDB(host=config.FALKORDB_HOST, port=config.FALKORDB_PORT, password=config.FALKORDB_PASSWORD,
                      socket_connect_timeout=config.FALKORDB_CONNECT_TIMEOUT_S)
        mine = TenantGraph(tg.tenant, db=db)
        barrier.wait()
        for t in task_ids:
            res = mine.write("task_claim", {"id": t, "agent": name, "until": 0})
            if res.result_set:
                with lock:
                    wins[t].append(name)
        db.close()

    threads = [threading.Thread(target=worker, args=(f"agent_{i}",)) for i in range(n_workers)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert all(len(w) == 1 for w in wins.values()), wins
    status = rows(tg.read("task_status", {"ids": task_ids}))
    assert all(s["status"] == "claimed" for s in status)
    assert {s["id"]: s["owner"] for s in status} == {t: w[0] for t, w in wins.items()}
