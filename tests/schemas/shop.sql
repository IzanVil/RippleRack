-- A small shop in MySQL: three tables, so one has to be chosen.
CREATE TABLE `customers` (
  `id` int NOT NULL AUTO_INCREMENT,
  `email` varchar(255) NOT NULL COMMENT 'Where the receipts go',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;

CREATE TABLE `order_items` (
  `order_id` int NOT NULL,
  `sku` varchar(32) NOT NULL,
  `quantity` smallint unsigned NOT NULL DEFAULT 1,
  `gift` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`order_id`, `sku`)
) ENGINE=InnoDB;

CREATE TABLE `OrderEvents` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `kind` enum('created','paid','shipped') NOT NULL,
  `at` datetime NOT NULL,
  `detail` json DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
