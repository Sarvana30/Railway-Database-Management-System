create database Railway_Management_System;

Use Railway_Management_System;

CREATE TABLE User (
	id INT PRIMARY KEY AUTO_INCREMENT,
	name VARCHAR(20) NOT NULL,
	phone VARCHAR(15) NOT NULL UNIQUE,
	gmail VARCHAR(20) UNIQUE NOT NULL,
	passwordHash VARCHAR(256) NOT NULL
);
 
CREATE TABLE station (
	id INT PRIMARY KEY AUTO_INCREMENT,
	name VARCHAR(20) NOT NULL,
	city VARCHAR(20) NOT NULL,
	state VARCHAR(20) NOT NULL,
	UNIQUE (name, city)
);
 
CREATE TABLE train (
	id INT PRIMARY KEY AUTO_INCREMENT,
	name VARCHAR(20) NOT NULL
);
 
CREATE TABLE coach (
	coachNo VARCHAR(5) NOT NULL,
	trainId INT NOT NULL,
	coachType ENUM('AC tier 1', 'AC tier 2', 'AC tier 3', 'Sleeper', '2s', 'cc') NOT NULL,
 
	PRIMARY KEY (coachNo, trainId),
 
	FOREIGN KEY (trainId)
		REFERENCES train (id)
		ON DELETE CASCADE
		ON UPDATE CASCADE
);
 
CREATE TABLE seat (
	id INT PRIMARY KEY AUTO_INCREMENT,
	seatNo VARCHAR(5) NOT NULL,
	coachNo VARCHAR(5) NOT NULL,
	trainId INT NOT NULL,
 
	FOREIGN KEY (coachNo, trainId)
		REFERENCES coach (coachNo, trainId)
		ON DELETE CASCADE
		ON UPDATE CASCADE,
 
	UNIQUE (coachNo, trainId, seatNo)
);
 
CREATE TABLE trainStop (
	trainId INT NOT NULL,
	stationId INT NOT NULL,
	arrivesAt DATETIME,
	departsAt DATETIME,
	stopSequence INT NOT NULL,
 
	PRIMARY KEY (trainId, stationId),
 
	FOREIGN KEY (trainId)
		REFERENCES train (id)
		ON DELETE CASCADE
		ON UPDATE CASCADE,
 
	FOREIGN KEY (stationId)
		REFERENCES station (id)
		ON DELETE RESTRICT
		ON UPDATE CASCADE,
 
	UNIQUE (trainId, stationId),
	CHECK (stopSequence > 0),
	CHECK (arrivesAt IS NULL OR departsAt IS NULL OR departsAt >= arrivesAt)  
);
 
CREATE TABLE ticket (
	ticketId INT PRIMARY KEY AUTO_INCREMENT,
	userId INT NOT NULL,
	trainId INT NOT NULL,
	startStationId INT NOT NULL,
	endStationId INT NOT NULL,
	bookedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
	journeyDate DATE NOT NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'BOOKED',
 
	FOREIGN KEY (userId)
		REFERENCES User (id)
		ON DELETE RESTRICT
		ON UPDATE CASCADE,
 
	FOREIGN KEY (trainId)
		REFERENCES train (id)
		ON DELETE RESTRICT
		ON UPDATE CASCADE,
 
	FOREIGN KEY (startStationId)
		REFERENCES station (id)
		ON DELETE RESTRICT
		ON UPDATE RESTRICT,  
        
	FOREIGN KEY (endStationId)
		REFERENCES station (id)
		ON DELETE RESTRICT
		ON UPDATE RESTRICT,  
 
	CHECK (startStationId != endStationId)
);
 
CREATE TABLE IF NOT EXISTS passenger (
	ticketId INT NOT NULL,
	passengerNo INT NOT NULL,
	name VARCHAR(20) NOT NULL,
	age INT NOT NULL,
	gender VARCHAR(10),
 
	PRIMARY KEY (ticketId, passengerNo),
 
	FOREIGN KEY (ticketId)
		REFERENCES ticket (ticketId)
		ON DELETE CASCADE
		ON UPDATE CASCADE,
 
	CHECK (passengerNo > 0),
	CHECK (age >= 0)
);
 
CREATE TABLE IF NOT EXISTS seatLeg (
	id INT PRIMARY KEY AUTO_INCREMENT,
	ticketId INT NOT NULL,
	seatId INT NOT NULL,
	fromStationId INT NOT NULL,
	toStationId INT NOT NULL,
 
	FOREIGN KEY (ticketId)
		REFERENCES ticket (ticketId)
		ON DELETE CASCADE
		ON UPDATE CASCADE,
 
	FOREIGN KEY (seatId)
		REFERENCES seat (id)
		ON DELETE RESTRICT
		ON UPDATE CASCADE,
 
	FOREIGN KEY (fromStationId)
		REFERENCES station (id)
		ON DELETE RESTRICT
		ON UPDATE RESTRICT,  
 
	FOREIGN KEY (toStationId)
		REFERENCES station (id)
		ON DELETE RESTRICT
		ON UPDATE RESTRICT,  
	CHECK (fromStationId != toStationId)
);