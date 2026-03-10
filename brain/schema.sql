CREATE TABLE
  `_migrations` (
    file VARCHAR(255) PRIMARY KEY NOT NULL,
    applied INTEGER NOT NULL
  );

CREATE TABLE
  `_params` (
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `value` JSON DEFAULT NULL,
    `created` TEXT DEFAULT (strftime ('%Y-%m-%d %H:%M:%fZ')) NOT NULL,
    `updated` TEXT DEFAULT (strftime ('%Y-%m-%d %H:%M:%fZ')) NOT NULL
  );

CREATE TABLE
  `_collections` (
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `system` BOOLEAN DEFAULT FALSE NOT NULL,
    `type` TEXT DEFAULT "base" NOT NULL,
    `name` TEXT UNIQUE NOT NULL,
    `fields` JSON DEFAULT "[]" NOT NULL,
    `indexes` JSON DEFAULT "[]" NOT NULL,
    `listRule` TEXT DEFAULT NULL,
    `viewRule` TEXT DEFAULT NULL,
    `createRule` TEXT DEFAULT NULL,
    `updateRule` TEXT DEFAULT NULL,
    `deleteRule` TEXT DEFAULT NULL,
    `options` JSON DEFAULT "{}" NOT NULL,
    `created` TEXT DEFAULT (strftime ('%Y-%m-%d %H:%M:%fZ')) NOT NULL,
    `updated` TEXT DEFAULT (strftime ('%Y-%m-%d %H:%M:%fZ')) NOT NULL
  );

CREATE INDEX idx__collections_type on `_collections` (`type`);

CREATE TABLE
  `_mfas` (
    `collectionRef` TEXT DEFAULT '' NOT NULL,
    `created` TEXT DEFAULT '' NOT NULL,
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `method` TEXT DEFAULT '' NOT NULL,
    `recordRef` TEXT DEFAULT '' NOT NULL,
    `updated` TEXT DEFAULT '' NOT NULL
  );

CREATE INDEX `idx_mfas_collectionRef_recordRef` ON `_mfas` (`collectionRef`, `recordRef`);

CREATE TABLE
  sqlite_stat1 (tbl, idx, stat);

CREATE TABLE
  sqlite_stat4 (tbl, idx, neq, nlt, ndlt, sample);

CREATE TABLE
  `_otps` (
    `collectionRef` TEXT DEFAULT '' NOT NULL,
    `created` TEXT DEFAULT '' NOT NULL,
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `password` TEXT DEFAULT '' NOT NULL,
    `recordRef` TEXT DEFAULT '' NOT NULL,
    `sentTo` TEXT DEFAULT '' NOT NULL,
    `updated` TEXT DEFAULT '' NOT NULL
  );

CREATE INDEX `idx_otps_collectionRef_recordRef` ON `_otps` (`collectionRef`, `recordRef`);

CREATE TABLE
  `_externalAuths` (
    `collectionRef` TEXT DEFAULT '' NOT NULL,
    `created` TEXT DEFAULT '' NOT NULL,
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `provider` TEXT DEFAULT '' NOT NULL,
    `providerId` TEXT DEFAULT '' NOT NULL,
    `recordRef` TEXT DEFAULT '' NOT NULL,
    `updated` TEXT DEFAULT '' NOT NULL
  );

CREATE UNIQUE INDEX `idx_externalAuths_record_provider` ON `_externalAuths` (`collectionRef`, `recordRef`, `provider`);

CREATE UNIQUE INDEX `idx_externalAuths_collection_provider` ON `_externalAuths` (`collectionRef`, `provider`, `providerId`);

CREATE TABLE
  `_authOrigins` (
    `collectionRef` TEXT DEFAULT '' NOT NULL,
    `created` TEXT DEFAULT '' NOT NULL,
    `fingerprint` TEXT DEFAULT '' NOT NULL,
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `recordRef` TEXT DEFAULT '' NOT NULL,
    `updated` TEXT DEFAULT '' NOT NULL
  );

CREATE UNIQUE INDEX `idx_authOrigins_unique_pairs` ON `_authOrigins` (`collectionRef`, `recordRef`, `fingerprint`);

CREATE TABLE
  `_superusers` (
    `created` TEXT DEFAULT '' NOT NULL,
    `email` TEXT DEFAULT '' NOT NULL,
    `emailVisibility` BOOLEAN DEFAULT FALSE NOT NULL,
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `password` TEXT DEFAULT '' NOT NULL,
    `tokenKey` TEXT DEFAULT '' NOT NULL,
    `updated` TEXT DEFAULT '' NOT NULL,
    `verified` BOOLEAN DEFAULT FALSE NOT NULL
  );

CREATE UNIQUE INDEX `idx_tokenKey_pbc_3142635823` ON `_superusers` (`tokenKey`);

CREATE UNIQUE INDEX `idx_email_pbc_3142635823` ON `_superusers` (`email`)
WHERE
  `email` != '';

CREATE TABLE
  `accounts` (
    `banned` BOOLEAN DEFAULT FALSE NOT NULL,
    `created` TEXT DEFAULT '' NOT NULL,
    `description` TEXT DEFAULT '' NOT NULL,
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `name` TEXT DEFAULT '' NOT NULL,
    `password` TEXT DEFAULT '' NOT NULL,
    `skins` BOOLEAN DEFAULT FALSE NOT NULL,
    `tag` TEXT DEFAULT '' NOT NULL,
    `updated` TEXT DEFAULT '' NOT NULL,
    `username` TEXT DEFAULT '' NOT NULL,
    "last_sale" TEXT DEFAULT '' NOT NULL,
    "cliente" TEXT DEFAULT '' NOT NULL,
    "email" TEXT DEFAULT '' NOT NULL,
    "recovery_blocked" BOOLEAN DEFAULT FALSE NOT NULL,
    "current_rank" TEXT DEFAULT '' NOT NULL,
    "highest_rank" TEXT DEFAULT '' NOT NULL,
    "ranking_in_tier" NUMERIC DEFAULT 0 NOT NULL,
    "last_update" TEXT DEFAULT '' NOT NULL,
    "account_level" NUMERIC DEFAULT 0 NOT NULL,
    "last_match" TEXT DEFAULT '' NOT NULL,
    "puuid" TEXT DEFAULT '' NOT NULL,
    "revenda_proibida" BOOLEAN DEFAULT FALSE NOT NULL
  );

CREATE TABLE
  `vendas` (
    `created` TEXT DEFAULT '' NOT NULL,
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `updated` TEXT DEFAULT '' NOT NULL,
    "venda" TEXT DEFAULT '' NOT NULL,
    "comprador" TEXT DEFAULT '' NOT NULL,
    "status" TEXT DEFAULT '' NOT NULL,
    "quantidade" NUMERIC DEFAULT 0 NOT NULL,
    "subtotal" NUMERIC DEFAULT 0 NOT NULL,
    "data" TEXT DEFAULT '' NOT NULL
  );

CREATE VIEW
  `ggmax` AS
SELECT
  *
FROM
  (
    SELECT
      id,
      puuid,
      username,
      password,
      description,
      current_rank,
      highest_rank,
      ranking_in_tier,
      last_match,
      last_update,
      last_sale
    FROM
      accounts
    WHERE
      last_sale != ''
      AND last_sale < date ('now', '-30 days')
      AND last_match != ''
      AND last_match < date ('now', '-30 days')
      AND banned = FALSE
      AND recovery_blocked = FALSE
      AND skins = FALSE
      AND revenda_proibida = FALSE
  )
  /* ggmax(id,puuid,username,password,description,current_rank,highest_rank,ranking_in_tier,last_match,last_update,last_sale) */;

CREATE VIEW
  `extrato` AS
SELECT
  *
FROM
  (
    SELECT
      CAST(`id` as TEXT) `id`,
      `mes`,
      `totalSubtotal`,
      `totalAcumulado`
    FROM
      (
        SELECT
          (ROW_NUMBER() OVER ()) as id,
          (
            CASE strftime ('%m', `data`)
              WHEN '01' THEN 'Janeiro'
              WHEN '02' THEN 'Fevereiro'
              WHEN '03' THEN 'Março'
              WHEN '04' THEN 'Abril'
              WHEN '05' THEN 'Maio'
              WHEN '06' THEN 'Junho'
              WHEN '07' THEN 'Julho'
              WHEN '08' THEN 'Agosto'
              WHEN '09' THEN 'Setembro'
              WHEN '10' THEN 'Outubro'
              WHEN '11' THEN 'Novembro'
              WHEN '12' THEN 'Dezembro'
            END || ' de ' || strftime ('%Y', `data`)
          ) AS mes,
          ROUND(SUM(`subtotal`), 2) AS totalSubtotal,
          (
            ROUND(
              SUM(SUM(`subtotal`)) OVER (
                ORDER BY
                  strftime ('%Y-%m', `data`)
              ),
              2
            )
          ) AS totalAcumulado
        FROM
          `vendas`
        GROUP BY
          strftime ('%Y-%m', `data`)
        ORDER BY
          mes
      )
  )
  /* extrato(id,mes,totalSubtotal,totalAcumulado) */;

CREATE UNIQUE INDEX `idx_cKSmIuHkAF` ON `accounts` (`username`);

CREATE TABLE
  IF NOT EXISTS "fazenda" (
    `created` TEXT DEFAULT '' NOT NULL,
    `id` TEXT PRIMARY KEY DEFAULT ('r' || lower(hex (randomblob (7)))) NOT NULL,
    `nivel` NUMERIC DEFAULT 0 NOT NULL,
    `puuid` TEXT DEFAULT '' NOT NULL,
    `senha` TEXT DEFAULT '' NOT NULL,
    `ultimo_login` TEXT DEFAULT '' NOT NULL,
    `updated` TEXT DEFAULT '' NOT NULL,
    `usuario` TEXT DEFAULT '' NOT NULL,
    "screenshot" TEXT DEFAULT '' NOT NULL
  );