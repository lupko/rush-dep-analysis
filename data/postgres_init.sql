--
-- Once you prepare_graph.sh and there are csv files available in this data dir, connect to postgres
-- and run this script. it will initialize the tables, load data, setup indexes and views.
--

DROP TABLE IF EXISTS node CASCADE;
CREATE TABLE node
(
    id       INTEGER NOT NULL PRIMARY KEY,
    value    TEXT,
    is_label INTEGER NOT NULL DEFAULT 0
);

COPY node (id, value, is_label)
    FROM '/var/lib/postgresql/data/deps.node.csv'
    DELIMITER ','
    CSV;

CREATE INDEX node_values ON node (value);

DROP TABLE IF EXISTS edge CASCADE;
CREATE TABLE edge
(
    from_id INTEGER NOT NULL,
    to_id   INTEGER NOT NULL,
    type    TEXT    NOT NULL,

    FOREIGN KEY (from_id) REFERENCES node (id),
    FOREIGN KEY (to_id) REFERENCES node (id)
);

COPY edge (from_id, to_id, type)
    FROM '/var/lib/postgresql/data/deps.edge.csv'
    DELIMITER ','
    CSV;

CREATE INDEX from_by_type_idx ON edge (from_id, type);
CREATE INDEX to_by_type_idx ON edge (to_id, type);
CREATE INDEX type_and_from_idx ON edge (type, from_id);
CREATE INDEX type_and_to_idx ON edge (type, to_id);

ANALYZE;

--
-- Create views
--

-- list packages together with the number of installed versions
CREATE VIEW install_counts AS
SELECT fn.value AS package,
       COUNT(1) AS installs
FROM edge e
         INNER JOIN node fn on e.from_id = fn.id
WHERE e.type = 'has_version'
GROUP BY package;

-- list all dependencies
CREATE VIEW dependencies AS
SELECT fn.value AS from_node,
       tn.value AS to_node,
       e.type   AS type
FROM edge e
         INNER JOIN node fn on e.from_id = fn.id
         INNER JOIN node tn on e.to_id = tn.id
WHERE e.type IN ('depends_dev', 'depends_prod', 'depends_peer', 'depends_opt_peer');

-- list licenses of all installed packages
CREATE VIEW licenses AS
SELECT fn.value AS package_version,
       tn.value AS license
FROM edge e
         INNER JOIN node fn on fn.id = e.from_id
         INNER JOIN node tn on tn.id = e.to_id
WHERE type = 'license';

--
-- Create stored functions
--

DROP FUNCTION IF EXISTS forward_deps(from_dep text, init_dep_type text[], rec_dep_type text[]);

--
-- Stored function to traverse dependencies of a package in a forward direction. Populates forward_result_table temp
-- table with the result. The temp table will be dropped on commit.
--
-- Using recursive CTE is possible too, however it is extremely time-consuming. The dependency chains are wide
-- and deep. Often time repeating large subtrees of same dependencies. One way to cut down on the lengthy processing
-- is to not repeat the large subtrees. However to achieve that, the query must check for _all_ dependencies
-- traversed so far (which seems to be impossible with CTEs).
--
CREATE OR REPLACE FUNCTION forward_deps(from_dep text, init_dep_type text[],
                                        rec_dep_type text[] default array []::text[])
    RETURNS TABLE
            (
                dependency TEXT,
                level      INTEGER
            )
AS
$$
DECLARE
    current_level        INTEGER := 1;
    new_deps_to_traverse INTEGER := 0;
BEGIN
    CREATE TEMPORARY TABLE IF NOT EXISTS forward_result_table
    (
        dep_id INTEGER PRIMARY KEY,
        level  INTEGER
    ) ON COMMIT DROP;

    INSERT INTO forward_result_table (
        SELECT d.dep_id, 1
        FROM (SELECT DISTINCT e.to_id AS dep_id
              FROM edge e
                       INNER JOIN node n ON n.id = e.from_id AND n.value = from_dep AND
                                            e.type IN (SELECT unnest(init_dep_type)) AND
                                            -- this condition below is important to prevent excessive
                                            -- processing. it's impossible with CTEs
                                            e.to_id NOT IN (SELECT dep_id FROM forward_result_table)
             ) d
    );

    LOOP
        INSERT INTO forward_result_table (
            SELECT d.dep_id AS dep_id, current_level + 1 AS level
            FROM (
                     SELECT DISTINCT e.to_id AS dep_id
                     FROM edge e
                              INNER JOIN forward_result_table r
                                         ON r.level = current_level
                                             AND r.dep_id = e.from_id
                                             AND e.type IN (SELECT unnest(rec_dep_type))
                                             AND e.to_id NOT IN (SELECT dep_id FROM forward_result_table)) d
        );

        GET DIAGNOSTICS new_deps_to_traverse = ROW_COUNT;
        current_level := current_level + 1;

        IF new_deps_to_traverse = 0 then
            exit;
        END IF;
    END LOOP;

    RETURN QUERY SELECT n.value AS dependency, r.level AS level
                 FROM forward_result_table r
                          INNER JOIN node n ON n.id = r.dep_id;
END;
$$
    LANGUAGE plpgsql;

DROP FUNCTION IF EXISTS reverse_deps(from_dep text, init_dep_type text[], rec_dep_type text[]);
CREATE OR REPLACE FUNCTION reverse_deps(from_dep text, init_dep_type text[],
                                        rec_dep_type text[] default array []::text[])
    RETURNS TABLE
            (
                dependency TEXT,
                level      INTEGER
            )
AS
$$
DECLARE
    current_level        INTEGER := 1;
    new_deps_to_traverse INTEGER := 0;
BEGIN
    CREATE TEMPORARY TABLE IF NOT EXISTS reverse_result_table
    (
        dep_id INTEGER PRIMARY KEY,
        level  INTEGER
    ) ON COMMIT DROP;

-- insert
    INSERT INTO reverse_result_table (
        SELECT d.dep_id, 1
        FROM (SELECT DISTINCT e.from_id AS dep_id
              FROM edge e
                       INNER JOIN node n ON n.id = e.to_id AND n.value = from_dep AND
                                            e.type IN (SELECT unnest(init_dep_type)) AND
                                            e.from_id NOT IN (SELECT dep_id FROM reverse_result_table)
             ) d
    );

    LOOP
        INSERT INTO reverse_result_table (
            SELECT d.dep_id AS dep_id, current_level + 1 AS level
            FROM (
                     SELECT DISTINCT e.from_id AS dep_id
                     FROM edge e
                              INNER JOIN reverse_result_table r
                                         ON r.level = current_level
                                             AND r.dep_id = e.to_id
                                             AND e.type IN (SELECT unnest(rec_dep_type))
                                             AND e.from_id NOT IN (SELECT dep_id FROM reverse_result_table)) d
        );

        GET DIAGNOSTICS new_deps_to_traverse = ROW_COUNT;
        current_level := current_level + 1;

        IF new_deps_to_traverse = 0 then
            exit;
        END IF;
    END LOOP;

    RETURN QUERY SELECT n.value AS dependency, r.level AS level
                 FROM reverse_result_table r
                          INNER JOIN node n ON n.id = r.dep_id;
END;
$$
    LANGUAGE plpgsql;

COMMIT;
