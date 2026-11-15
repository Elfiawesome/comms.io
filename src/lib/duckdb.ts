import * as duckdb from '@duckdb/duckdb-wasm';
import duckdbMvpWasm from '@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url';
import mvpWorker from '@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url';
import duckdbEhWasm from '@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url';
import ehWorker from '@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url';

export interface DuckSession {
  db: duckdb.AsyncDuckDB;
  conn: duckdb.AsyncDuckDBConnection;
}

const bundles = {
  mvp: {
    mainModule: duckdbMvpWasm,
    mainWorker: mvpWorker
  },
  eh: {
    mainModule: duckdbEhWasm,
    mainWorker: ehWorker
  }
};

let sessionPromise: Promise<DuckSession> | null = null;

export function getDuckSession(): Promise<DuckSession> {
  if (!sessionPromise) {
    sessionPromise = createSession().catch((error) => {
      sessionPromise = null;
      throw error;
    });
  }
  return sessionPromise;
}

async function createSession(): Promise<DuckSession> {
  const bundle = await duckdb.selectBundle(bundles);
  if (!bundle.mainWorker) {
    throw new Error('DuckDB worker bundle is unavailable.');
  }
  const worker = new Worker(bundle.mainWorker);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  const conn = await db.connect();

  try {
    await conn.query('LOAD httpfs;');
  } catch {
    try {
      await conn.query('INSTALL httpfs; LOAD httpfs;');
    } catch (error) {
      // Queries against same-origin files can still work through the browser
      // filesystem in some builds; surface a useful warning if they do not.
      console.warn('DuckDB httpfs extension was not available.', error);
    }
  }

  return { db, conn };
}
