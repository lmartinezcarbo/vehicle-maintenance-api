# Vehicle Maintenance API

REST API for managing vehicles, maintenance records, parts, and expenses.

This project was built as a backend portfolio project to demonstrate practical experience with Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, authentication, authorization, testing, and Docker.

The API allows authenticated users to manage their own vehicle-related data while administrators have additional access according to the application's role-based authorization rules.

## Features

* User registration and management
* JWT-based authentication
* Password hashing
* Role-based authorization with `user` and `admin` roles
* Ownership-based access control
* Vehicle management
* Maintenance record management
* Parts management
* Maintenance parts management
* Expense management
* Input validation with Pydantic
* Filtering and query parameters
* Pagination
* Sorting
* Search functionality
* Automated API tests with pytest
* Health checks
* Application logging
* Relational data modeling with PostgreSQL
* Database migrations with Alembic
* Docker and Docker Compose support
* API documentation with Swagger UI and ReDoc

## Tech Stack

### Backend

* Python 3.14
* FastAPI
* Pydantic
* SQLAlchemy
* Alembic

### Database

* PostgreSQL 17

### Authentication & Security

* JWT
* Password hashing
* Role-based access control (RBAC)
* Ownership-based authorization

### Testing

* pytest

### DevOps & Tools

* Docker
* Docker Compose
* Git
* GitHub

### Documentation

* Swagger UI
* ReDoc
* Archify
