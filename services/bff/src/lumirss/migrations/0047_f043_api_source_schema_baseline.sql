-- 0047: F043 API source structure-drift baseline.
--
-- confirmed_schema — user-confirmed field baseline (JSON snapshot taken
-- when the mapping is saved/confirmed): {field: {"type": str, "required":
-- bool}}; bounded (≤64 fields, serialized ≤2KB).
-- schema_drift — last comparison result (JSON {missing, type_changed,
-- new_optional}); advisory only, never blocks serving.
ALTER TABLE api_sources ADD COLUMN confirmed_schema TEXT;
ALTER TABLE api_sources ADD COLUMN schema_drift TEXT;
