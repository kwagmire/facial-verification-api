package db

import (
	"log"

	"github.com/pressly/goose/v3"
)

func RunMigrations() {
	ConnectDB()
	// Specify the directory where your migration files are located
	//goose.SetDir("./migrations")

	// Run the migrations
	if err := goose.Up(DB, "./db/migrations"); err != nil {
		log.Fatalf("goose: failed to run migrations: %v\n", err)
	}

	log.Println("Database migrations applied successfully.")
}
