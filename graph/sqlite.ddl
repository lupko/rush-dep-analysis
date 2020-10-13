CREATE TABLE node (
    id INTEGER NOT NULL PRIMARY KEY,
    value TEXT NOT NULL,
    is_label INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX node_values ON node(value);

CREATE TABLE edge (
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    type TEXT NOT NULL,

    FOREIGN KEY (from_id) REFERENCES node(id),
    FOREIGN KEY (to_id) REFERENCES node(id)
);

CREATE INDEX from_idx ON edge(from_id);
CREATE INDEX to_idx ON edge(to_id);
CREATE INDEX type_idx ON edge(type);

CREATE INDEX from_by_type_idx ON edge(from_id, type);
CREATE INDEX to_by_type_idx ON edge(to_id, type);
CREATE INDEX type_and_from_idx ON edge(type, from_id);
CREATE INDEX type_and_to_idx ON edge(type, to_id);

--
-- Views
--

-- list subjects by the role they play (primary, package, dependency)
CREATE VIEW by_role AS
SELECT
    fn.value AS subject,
    tn.value AS role
FROM edge e
         INNER JOIN node fn on e.from_id = fn.id
         INNER JOIN node tn on e.to_id = tn.id
WHERE e.type == 'has_role';

-- list installed versions for packages
CREATE VIEW installed_versions AS
SELECT
    fn.value AS package,
    tn.value AS installed_version
FROM edge e
         INNER JOIN node fn on e.from_id = fn.id
         INNER JOIN node tn on e.to_id = tn.id
WHERE e.type = 'has_version';


-- list packages together with the number of installed versions
CREATE VIEW install_counts AS
SELECT
    fn.value AS package,
    COUNT(1) AS installs
FROM edge e
         INNER JOIN node fn on e.from_id = fn.id
WHERE e.type == 'has_version'
GROUP BY package;

-- list all dependencies
CREATE VIEW dependencies AS
SELECT
    fn.value AS from_node,
    tn.value AS to_node,
    e.type AS type
FROM edge e
         INNER JOIN node fn on e.from_id = fn.id
         INNER JOIN node tn on e.to_id = tn.id
WHERE e.type IN ('depends_dev', 'depends_prod', 'depends_peer', 'depends_opt_peer');

-- list licenses of all installed packages
CREATE VIEW licenses AS
SELECT
    fn.value AS package_version,
    tn.value AS license
FROM edge e
         INNER JOIN node fn on fn.id = e.from_id
         INNER JOIN node tn on tn.id = e.to_id
WHERE type = 'license';
