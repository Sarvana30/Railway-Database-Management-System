CREATE DATABASE IF NOT EXISTS railway_management_system;
USE railway_management_system;

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    gmail VARCHAR(254) NOT NULL,
    passwordHash VARCHAR(255) NOT NULL,
    createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_users_phone (phone),
    UNIQUE KEY uq_users_gmail (gmail)
);

CREATE TABLE station (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    UNIQUE KEY uq_station_name_city (name, city)
);

CREATE TABLE train (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trainNumber VARCHAR(20) NOT NULL,
    name VARCHAR(100) NOT NULL,
    trainType ENUM('SUPERFAST', 'EXPRESS', 'MAIL', 'PASSENGER') NOT NULL DEFAULT 'EXPRESS',
    UNIQUE KEY uq_train_number (trainNumber)
);

CREATE TABLE schedule_service_day (
    trainId INT NOT NULL,
    serviceDay TINYINT UNSIGNED NOT NULL,
    PRIMARY KEY (trainId, serviceDay),
    CONSTRAINT fk_schedule_service_day_train FOREIGN KEY (trainId)
        REFERENCES train (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT chk_schedule_service_day CHECK (serviceDay BETWEEN 1 AND 7)
);

CREATE TABLE train_schedule_stop (
    trainId INT NOT NULL,
    stationId INT NOT NULL,
    stopSequence INT NOT NULL,
    arrivalTime TIME NULL,
    departureTime TIME NULL,
    arrivalDayOffset SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    departureDayOffset SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (trainId, stationId),
    UNIQUE KEY uq_train_schedule_stop_sequence (trainId, stopSequence),
    CONSTRAINT fk_train_schedule_stop_train FOREIGN KEY (trainId)
        REFERENCES train (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_train_schedule_stop_station FOREIGN KEY (stationId)
        REFERENCES station (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CONSTRAINT chk_train_schedule_stop_sequence CHECK (stopSequence > 0),
    CONSTRAINT chk_train_schedule_stop_times CHECK (
        (arrivalTime IS NOT NULL OR departureTime IS NOT NULL) AND
        (arrivalTime IS NOT NULL OR arrivalDayOffset = 0) AND
        (departureTime IS NOT NULL OR departureDayOffset = 0)
    )
);

CREATE TABLE compartment (
    trainId INT NOT NULL,
    compartmentNo VARCHAR(10) NOT NULL,
    compartmentType ENUM('AC tier 1', 'AC tier 2', 'AC tier 3', 'Sleeper', '2s', 'cc') NOT NULL,
    PRIMARY KEY (trainId, compartmentNo),
    CONSTRAINT fk_compartment_train FOREIGN KEY (trainId)
        REFERENCES train (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE schedule_segment_distance (
    trainId INT NOT NULL,
    fromStationId INT NOT NULL,
    toStationId INT NOT NULL,
    distanceKm INT UNSIGNED NOT NULL,
    PRIMARY KEY (trainId, fromStationId, toStationId),
    CONSTRAINT chk_train_segment_distance CHECK (distanceKm > 0),
    CONSTRAINT fk_segment_distance_from_stop FOREIGN KEY (trainId, fromStationId)
        REFERENCES train_schedule_stop (trainId, stationId)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_segment_distance_to_stop FOREIGN KEY (trainId, toStationId)
        REFERENCES train_schedule_stop (trainId, stationId)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE fare_distance_slab (
    compartmentType ENUM('AC tier 1', 'AC tier 2', 'AC tier 3', 'Sleeper', '2s', 'cc') NOT NULL,
    minDistanceKm INT UNSIGNED NOT NULL,
    maxDistanceKm INT UNSIGNED NULL,
    ratePerKm DECIMAL(8, 4) NOT NULL,
    minimumBaseFare DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    PRIMARY KEY (compartmentType, minDistanceKm),
    CONSTRAINT chk_fare_slab_range CHECK (
        maxDistanceKm IS NULL OR maxDistanceKm >= minDistanceKm
    ),
    CONSTRAINT chk_fare_slab_rate CHECK (ratePerKm >= 0 AND minimumBaseFare >= 0)
);

CREATE TABLE reservation_fee (
    compartmentType ENUM('AC tier 1', 'AC tier 2', 'AC tier 3', 'Sleeper', '2s', 'cc') PRIMARY KEY,
    feeAmount DECIMAL(10, 2) NOT NULL,
    CONSTRAINT chk_reservation_fee CHECK (feeAmount >= 0)
);

CREATE TABLE train_type_charge (
    trainType ENUM('SUPERFAST', 'EXPRESS', 'MAIL', 'PASSENGER') NOT NULL,
    compartmentType ENUM('AC tier 1', 'AC tier 2', 'AC tier 3', 'Sleeper', '2s', 'cc') NOT NULL,
    chargeAmount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    PRIMARY KEY (trainType, compartmentType),
    CONSTRAINT chk_train_type_charge CHECK (chargeAmount >= 0)
);

CREATE TABLE train_type_fare_factor (
    trainType ENUM('SUPERFAST', 'EXPRESS', 'MAIL', 'PASSENGER') PRIMARY KEY,
    baseFareMultiplier DECIMAL(6, 3) NOT NULL,
    CONSTRAINT chk_train_type_fare_factor CHECK (baseFareMultiplier > 0)
);

CREATE TABLE fare_route_length_factor (
    minRouteDistanceKm INT UNSIGNED NOT NULL,
    maxRouteDistanceKm INT UNSIGNED NULL,
    fareMultiplier DECIMAL(6, 3) NOT NULL,
    PRIMARY KEY (minRouteDistanceKm),
    CONSTRAINT chk_route_factor_range CHECK (
        maxRouteDistanceKm IS NULL OR maxRouteDistanceKm >= minRouteDistanceKm
    ),
    CONSTRAINT chk_route_fare_multiplier CHECK (fareMultiplier > 0)
);

CREATE TABLE fare_tax_rate (
    compartmentType ENUM('AC tier 1', 'AC tier 2', 'AC tier 3', 'Sleeper', '2s', 'cc') PRIMARY KEY,
    gstPercent DECIMAL(5, 2) NOT NULL DEFAULT 0.00,
    CONSTRAINT chk_fare_gst_percent CHECK (gstPercent BETWEEN 0 AND 100)
);

CREATE TABLE seat (
    seatId INT AUTO_INCREMENT PRIMARY KEY,
    trainId INT NOT NULL,
    compartmentNo VARCHAR(10) NOT NULL,
    seatNo VARCHAR(10) NOT NULL,
    UNIQUE KEY uq_seat_compartment_number (trainId, compartmentNo, seatNo),
    UNIQUE KEY uq_seat_id_train (seatId, trainId),
    CONSTRAINT fk_seat_compartment FOREIGN KEY (trainId, compartmentNo)
        REFERENCES compartment (trainId, compartmentNo)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE train_run (
    trainRunId INT AUTO_INCREMENT PRIMARY KEY,
    trainId INT NOT NULL,
    serviceDate DATE NOT NULL,
    departureAt DATETIME NOT NULL,
    status ENUM('SCHEDULED', 'CANCELLED') NOT NULL DEFAULT 'SCHEDULED',
    UNIQUE KEY uq_train_run_train_date (trainId, serviceDate),
    UNIQUE KEY uq_train_run_id_train (trainRunId, trainId),
    KEY idx_train_run_departure (departureAt, status),
    CONSTRAINT fk_train_run_train FOREIGN KEY (trainId)
        REFERENCES train (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
);

CREATE TABLE trainStop (
    trainRunId INT NOT NULL,
    trainId INT NOT NULL,
    stationId INT NOT NULL,
    stopSequence INT NOT NULL,
    arrivalAt DATETIME NULL,
    departureAt DATETIME NULL,
    PRIMARY KEY (trainRunId, stationId),
    UNIQUE KEY uq_train_stop_sequence (trainRunId, stopSequence),
    UNIQUE KEY uq_train_stop_run_train_station (trainRunId, trainId, stationId),
    KEY idx_train_stop_station (stationId, trainRunId),
    CONSTRAINT fk_train_stop_run_train FOREIGN KEY (trainRunId, trainId)
        REFERENCES train_run (trainRunId, trainId)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_train_stop_station FOREIGN KEY (stationId)
        REFERENCES station (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CONSTRAINT chk_train_stop_sequence CHECK (stopSequence > 0),
    CONSTRAINT chk_train_stop_times CHECK (
        arrivalAt IS NULL OR departureAt IS NULL OR departureAt >= arrivalAt
    )
);

CREATE TABLE ticket (
    ticketId INT AUTO_INCREMENT PRIMARY KEY,
    userId INT NOT NULL,
    trainRunId INT NOT NULL,
    trainId INT NOT NULL,
    startStationId INT NOT NULL,
    endStationId INT NOT NULL,
    ticketType ENUM('GENERAL', 'TATKAL', 'LADIES', 'SENIOR') NOT NULL DEFAULT 'GENERAL',
    status ENUM('CONFIRMED', 'CANCELLED') NOT NULL DEFAULT 'CONFIRMED',
    paymentStatus ENUM('PENDING', 'PAID', 'REFUNDED') NOT NULL DEFAULT 'PAID',
    fareModel ENUM('LEGACY', 'DISTANCE_SLAB') NOT NULL DEFAULT 'DISTANCE_SLAB',
    distanceKm INT UNSIGNED NOT NULL DEFAULT 0,
    trainRouteDistanceKm INT UNSIGNED NOT NULL DEFAULT 0,
    trainTypeFareMultiplier DECIMAL(6, 3) NOT NULL DEFAULT 1.000,
    routeLengthFareMultiplier DECIMAL(6, 3) NOT NULL DEFAULT 1.000,
    baseFareAmount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    reservationFeeAmount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    superfastChargeAmount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    gstAmount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    fareRoundingAmount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    fareAmount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    refundStatus ENUM('NONE', 'REFUNDED') NOT NULL DEFAULT 'NONE',
    bookedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ticket_id_run_train (ticketId, trainRunId, trainId),
    KEY idx_ticket_user_booked (userId, bookedAt),
    KEY idx_ticket_run_status (trainRunId, status),
    CONSTRAINT fk_ticket_user FOREIGN KEY (userId)
        REFERENCES users (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CONSTRAINT fk_ticket_run_train FOREIGN KEY (trainRunId, trainId)
        REFERENCES train_run (trainRunId, trainId)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CONSTRAINT fk_ticket_start_stop FOREIGN KEY (trainRunId, trainId, startStationId)
        REFERENCES trainStop (trainRunId, trainId, stationId)
        ON DELETE RESTRICT,
    CONSTRAINT fk_ticket_end_stop FOREIGN KEY (trainRunId, trainId, endStationId)
        REFERENCES trainStop (trainRunId, trainId, stationId)
        ON DELETE RESTRICT
);

CREATE TABLE passenger (
    ticketId INT NOT NULL,
    passengerNo INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    age TINYINT UNSIGNED NOT NULL,
    gender ENUM('F', 'M', 'OTHER', 'UNSPECIFIED') NOT NULL DEFAULT 'UNSPECIFIED',
    PRIMARY KEY (ticketId, passengerNo),
    CONSTRAINT fk_passenger_ticket FOREIGN KEY (ticketId)
        REFERENCES ticket (ticketId)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT chk_passenger_number CHECK (passengerNo > 0)
);

CREATE TABLE seat_leg (
    ticketId INT NOT NULL,
    passengerNo INT NOT NULL,
    legNo INT NOT NULL,
    trainRunId INT NOT NULL,
    trainId INT NOT NULL,
    seatId INT NOT NULL,
    fromStationId INT NOT NULL,
    toStationId INT NOT NULL,
    PRIMARY KEY (ticketId, passengerNo, legNo),
    KEY idx_seat_leg_availability (seatId, trainRunId, fromStationId, toStationId),
    CONSTRAINT fk_seat_leg_passenger FOREIGN KEY (ticketId, passengerNo)
        REFERENCES passenger (ticketId, passengerNo)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_seat_leg_ticket_run FOREIGN KEY (ticketId, trainRunId, trainId)
        REFERENCES ticket (ticketId, trainRunId, trainId)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_seat_leg_seat_train FOREIGN KEY (seatId, trainId)
        REFERENCES seat (seatId, trainId)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CONSTRAINT fk_seat_leg_from_stop FOREIGN KEY (trainRunId, trainId, fromStationId)
        REFERENCES trainStop (trainRunId, trainId, stationId)
        ON DELETE RESTRICT,
    CONSTRAINT fk_seat_leg_to_stop FOREIGN KEY (trainRunId, trainId, toStationId)
        REFERENCES trainStop (trainRunId, trainId, stationId)
        ON DELETE RESTRICT,
    CONSTRAINT chk_seat_leg_number CHECK (legNo > 0)
);

CREATE TABLE booking_hold (
    holdId BIGINT AUTO_INCREMENT PRIMARY KEY,
    holdToken VARCHAR(64) NOT NULL,
    userId INT NOT NULL,
    trainRunId INT NOT NULL,
    trainId INT NOT NULL,
    startStationId INT NOT NULL,
    endStationId INT NOT NULL,
    seatCategory ENUM('AC tier 1', 'AC tier 2', 'AC tier 3', 'Sleeper', '2s', 'cc') NOT NULL,
    ticketType ENUM('GENERAL', 'TATKAL', 'LADIES', 'SENIOR') NOT NULL,
    passengerCount SMALLINT UNSIGNED NOT NULL,
    expiresAt DATETIME NOT NULL,
    status ENUM('ACTIVE', 'CONSUMED', 'RELEASED') NOT NULL DEFAULT 'ACTIVE',
    ticketId INT NULL,
    createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_booking_hold_token (holdToken),
    UNIQUE KEY uq_booking_hold_ticket (ticketId),
    KEY idx_booking_hold_run_expiry (trainRunId, status, expiresAt),
    CONSTRAINT fk_booking_hold_user FOREIGN KEY (userId)
        REFERENCES users (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_booking_hold_run_train FOREIGN KEY (trainRunId, trainId)
        REFERENCES train_run (trainRunId, trainId)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_booking_hold_start_stop FOREIGN KEY (trainRunId, trainId, startStationId)
        REFERENCES trainStop (trainRunId, trainId, stationId)
        ON DELETE CASCADE,
    CONSTRAINT fk_booking_hold_end_stop FOREIGN KEY (trainRunId, trainId, endStationId)
        REFERENCES trainStop (trainRunId, trainId, stationId)
        ON DELETE CASCADE,
    CONSTRAINT fk_booking_hold_ticket FOREIGN KEY (ticketId)
        REFERENCES ticket (ticketId)
        ON DELETE SET NULL,
    CONSTRAINT chk_booking_hold_passenger_count CHECK (passengerCount > 0)
);

CREATE TABLE booking_hold_seat (
    holdId BIGINT NOT NULL,
    trainRunId INT NOT NULL,
    trainId INT NOT NULL,
    seatId INT NOT NULL,
    fromStationId INT NOT NULL,
    toStationId INT NOT NULL,
    PRIMARY KEY (holdId, seatId),
    KEY idx_booking_hold_seat_lookup (seatId, fromStationId, toStationId),
    CONSTRAINT fk_booking_hold_seat_hold FOREIGN KEY (holdId)
        REFERENCES booking_hold (holdId)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_booking_hold_seat_seat FOREIGN KEY (seatId, trainId)
        REFERENCES seat (seatId, trainId)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_booking_hold_seat_from_stop FOREIGN KEY (trainRunId, trainId, fromStationId)
        REFERENCES trainStop (trainRunId, trainId, stationId)
        ON DELETE CASCADE,
    CONSTRAINT fk_booking_hold_seat_to_stop FOREIGN KEY (trainRunId, trainId, toStationId)
        REFERENCES trainStop (trainRunId, trainId, stationId)
        ON DELETE CASCADE
);
