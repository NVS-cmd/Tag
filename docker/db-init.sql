-- Выполняется один раз при создании базы.
-- btree_gist нужен для запрета пересечений сеансов по комнате и мастеру.
-- Ставим и в рабочую базу, и в template1 — оттуда его получит тестовая база.
CREATE EXTENSION IF NOT EXISTS btree_gist;
\c template1
CREATE EXTENSION IF NOT EXISTS btree_gist;
