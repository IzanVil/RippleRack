-- Every kind of column that imports without --lenient, in PostgreSQL.
CREATE TYPE public.mood AS ENUM ('sad', 'ok', 'happy');

CREATE TABLE public.kitchen_sink (
    id            bigserial PRIMARY KEY,
    small         smallint NOT NULL,
    counter       integer GENERATED ALWAYS AS IDENTITY,
    whole_money   numeric(12),
    price         numeric(12, 2) NOT NULL,
    anything      numeric,
    ratio         double precision,
    flag          boolean NOT NULL,
    bits          bit(1),
    name          character varying(120) NOT NULL,
    notes         text,
    email         citext,
    token         uuid DEFAULT gen_random_uuid() NOT NULL,
    raw           bytea,
    address       inet,
    started       time,
    elapsed       interval,
    born          date,
    created_at    timestamp without time zone NOT NULL,
    seen_at       timestamp with time zone,
    meta          jsonb,
    tags          text[],
    feeling       public.mood NOT NULL
);

COMMENT ON COLUMN public.kitchen_sink.price IS 'Price,   in euros';
COMMENT ON COLUMN public.kitchen_sink.feeling IS 'How the customer felt';
