-- ==========================================
-- COFFEE SHOP AI DATABASE
-- ==========================================

DROP DATABASE IF EXISTS coffee_shop;
CREATE DATABASE coffee_shop;
USE coffee_shop;

-- ==========================================
-- USERS
-- ==========================================

CREATE TABLE users (

    id INT AUTO_INCREMENT PRIMARY KEY,

    fullname VARCHAR(100) NOT NULL,

    username VARCHAR(50) NOT NULL UNIQUE,

    password VARCHAR(255) NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);

-- ==========================================
-- PRODUCTS
-- ==========================================

CREATE TABLE products (

    id INT AUTO_INCREMENT PRIMARY KEY,

    name VARCHAR(100) NOT NULL,

    category VARCHAR(50) NOT NULL,

    price DECIMAL(10,2) NOT NULL,

    image VARCHAR(255) NOT NULL,

    description TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);

-- ==========================================
-- ORDERS
-- ==========================================

CREATE TABLE orders (

    id INT AUTO_INCREMENT PRIMARY KEY,

    customer_name VARCHAR(100) NOT NULL,

    product_name VARCHAR(100) NOT NULL,

    quantity INT NOT NULL,

    price DECIMAL(10,2) NOT NULL,

    total DECIMAL(10,2) NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);

-- ==========================================
-- SAMPLE ADMIN
-- Username : admin
-- Password : admin123
-- ==========================================

INSERT INTO users
(fullname, username, password)

VALUES

(
'System Administrator',
'admin',
'admin123'
);

-- ==========================================
-- SAMPLE PRODUCTS
-- ==========================================

INSERT INTO products
(name, category, price, image, description)

VALUES

(
'Cappuccino',
'Coffee',
180,
'cappuccino.jpg',
'Espresso with steamed milk and milk foam.'
),

(
'Caffe Latte',
'Coffee',
190,
'latte.jpg',
'Smooth espresso mixed with steamed milk.'
),

(
'Americano',
'Coffee',
150,
'americano.jpg',
'Rich espresso diluted with hot water.'
),

(
'Espresso',
'Coffee',
120,
'espresso.jpg',
'Strong pure espresso shot.'
),

(
'Mocha',
'Coffee',
200,
'mocha.jpg',
'Espresso with chocolate and steamed milk.'
),

(
'Caramel Macchiato',
'Coffee',
220,
'macchiato.jpg',
'Espresso with vanilla syrup and caramel.'
),

(
'Vanilla Frappuccino',
'Frappuccino',
240,
'frappuccino.jpg',
'Blended vanilla coffee with whipped cream.'
),

(
'Iced Coffee',
'Cold Coffee',
140,
'icedcoffee.jpg',
'Refreshing cold brewed coffee.'
),

(
'Cheesecake',
'Dessert',
160,
'cheesecake.jpg',
'Creamy baked cheesecake.'
),

(
'Chocolate Cake',
'Dessert',
170,
'chocolatecake.jpg',
'Rich chocolate cake.'
),

(
'Blueberry Muffin',
'Dessert',
95,
'muffin.jpg',
'Freshly baked blueberry muffin.'
),

(
'Croissant',
'Bread',
85,
'croissant.jpg',
'Buttery flaky croissant.'
);

-- ==========================================
-- CHECK DATA
-- ==========================================

SELECT * FROM users;
SELECT * FROM products;
SELECT * FROM orders;