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
    _db = new Database(DB_PATH, { readonly: true });
    _db.pragma("journal_mode = WAL");
  }
  return _db;
}
