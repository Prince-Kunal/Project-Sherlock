-- Separate database for the test suite so `make test` never touches dev data.
CREATE DATABASE sherlock_test OWNER sherlock;
