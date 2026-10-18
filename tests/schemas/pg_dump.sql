--
-- PostgreSQL database dump
--

-- Dumped from database version 16.2
-- Dumped by pg_dump version 16.2

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET default_tablespace = '';
SET default_table_access_method = heap;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;
COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';

CREATE TYPE public.order_status AS ENUM (
    'pending',
    'paid',
    'refunded'
);
ALTER TYPE public.order_status OWNER TO app;

CREATE FUNCTION public.touch() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;
ALTER FUNCTION public.touch() OWNER TO app;

CREATE TABLE public.customers (
    id integer NOT NULL,
    email character varying(255) NOT NULL,
    name text
);
ALTER TABLE public.customers OWNER TO app;

CREATE SEQUENCE public.customers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER TABLE public.customers_id_seq OWNER TO app;
ALTER SEQUENCE public.customers_id_seq OWNED BY public.customers.id;

CREATE TABLE public.orders (
    id bigint NOT NULL,
    customer_id integer NOT NULL,
    status public.order_status DEFAULT 'pending'::public.order_status NOT NULL,
    amount numeric(12,2),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    meta jsonb
);
ALTER TABLE public.orders OWNER TO app;
COMMENT ON COLUMN public.orders.amount IS 'Order total';
COMMENT ON TABLE public.orders IS 'All orders';

ALTER TABLE ONLY public.customers ALTER COLUMN id SET DEFAULT nextval('public.customers_id_seq'::regclass);
ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id);
CREATE INDEX idx_orders_status ON public.orders USING btree (status);
CREATE TRIGGER touch BEFORE UPDATE ON public.orders FOR EACH ROW EXECUTE FUNCTION public.touch();
CREATE VIEW public.paid_orders AS SELECT id, amount FROM public.orders WHERE status = 'paid';
GRANT SELECT ON TABLE public.orders TO readonly;

--
-- PostgreSQL database dump complete
--
