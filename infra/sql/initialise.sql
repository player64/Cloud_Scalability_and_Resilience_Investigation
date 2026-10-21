-- One-time operation on an empty servicedb, through coupon-operator.py init.
-- The operator helper supplies @app_password from SSM in the same session.
-- Deliberately no IF NOT EXISTS, destructive cleanup or reseeding behaviour.
USE servicedb;
SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_BACKSLASH_ESCAPES';

CREATE TABLE coupon (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(255) UNIQUE,
    discount DECIMAL(19,2),
    exp_date VARCHAR(255)
) ENGINE=InnoDB;

CREATE TABLE product (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255),
    description VARCHAR(255),
    price DECIMAL(19,2),
    coupon_code VARCHAR(255)
) ENGINE=InnoDB;

-- Double single quotes within the password for SQL escaping; backslashes
-- are literal under NO_BACKSLASH_ESCAPES. No password is committed here.
SET @create_user = CONCAT(
    'CREATE USER ''ca1_app''@''%'' IDENTIFIED BY ''',
    REPLACE(@app_password, '''', ''''''), ''''
);
PREPARE create_app_user FROM @create_user;
EXECUTE create_app_user;
DEALLOCATE PREPARE create_app_user;
SET @create_user = NULL, @app_password = NULL;
GRANT SELECT, INSERT, UPDATE, DELETE ON servicedb.* TO 'ca1_app'@'%';

START TRANSACTION;
INSERT INTO coupon (id, code, discount, exp_date)
VALUES (1, 'SAVE10', 10.00, '2030-12-31');
INSERT INTO product (id, name, description, price, coupon_code) VALUES
    (1, 'Keyboard', 'Wired keyboard', 90.00, 'SAVE10'),
    (2, 'Mouse', 'Optical mouse', 40.00, 'SAVE10');
COMMIT;

ALTER TABLE product AUTO_INCREMENT = 3;
ALTER TABLE coupon AUTO_INCREMENT = 2;
