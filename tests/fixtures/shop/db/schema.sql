CREATE TABLE orders (id text PRIMARY KEY, status text NOT NULL);
CREATE TABLE order_events (id serial PRIMARY KEY, order_id text REFERENCES orders ON DELETE CASCADE);
