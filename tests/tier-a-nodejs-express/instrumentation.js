/**
 * EDOT Node.js auto-instrumentation bootstrap.
 * This file must be required BEFORE any other imports via --require flag.
 * EDOT auto-instruments: Express, http, https, pg, mysql2, redis, amqplib, grpc-js
 */
require('@elastic/opentelemetry-node');
