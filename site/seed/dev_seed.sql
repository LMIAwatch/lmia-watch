-- SAMPLE DATA for the two site-owned tables. Everything else the site reads
-- comes from the static JSON under public/data (see `npm run data:local`).
-- The employer ids match the sample profiles in test/fixtures.

INSERT INTO employer_responses (employer_id, received_at, contact_name, contact_email, statement, verified, published) VALUES
  ('emp-a000000001', '2026-10-13T15:00:00Z', 'Owner', 'owner@example.com',
   'We have operated as a sole proprietorship since 2018 and incorporated in June 2026 for insurance reasons.', 1, 1),
  ('emp-a000000001', '2026-10-14T09:00:00Z', 'Owner', 'owner@example.com', 'A second statement that is still under review.', 0, 0);

INSERT INTO corrections (employer_id, record_ref, received_at, request, contact_email, resolution, resolved_at, published) VALUES
  ('emp-a000000002', 'Job Bank 50440025', '2026-10-13T16:00:00Z', 'The street address shown is the old location.', NULL,
   'Street updated from the current posting.', '2026-10-14T10:00:00Z', 1);
