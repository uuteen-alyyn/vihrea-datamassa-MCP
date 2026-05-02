import Database from "better-sqlite3";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// DB_PATH ympäristömuuttujasta tai oletuspolusta projektin juureen
const DB_PATH =
  process.env["DB_PATH"] ??
  resolve(__dirname, "../../data/green_data.db");

// Singleton-yhteys — avataan kerran, pidetään auki koko prosessin ajan
let _db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (!_db) {
    // Read-only open. The pipeline builds the DB in DELETE journal mode
    // (see pipeline/build_db.py — switched back from WAL before close)
    // specifically so this open works against a `:ro`-mounted volume in
    // production: a WAL-mode DB needs writable `.db-wal` and `.db-shm`
    // sidecar files even for readonly access, which a read-only mount
    // blocks (SQLITE_CANTOPEN). DELETE-mode DBs are self-contained.
    //
    // Don't attempt PRAGMA journal_mode=WAL here. SQLite will silently
    // ignore writes on a readonly connection, but a stale instruction in
    // this code path masked the underlying mount issue when we hit it.
    _db = new Database(DB_PATH, { readonly: true });
  }
  return _db;
}
