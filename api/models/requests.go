package models

type RegisterUserPayload struct {
	Email        string `json:"email"`
	FirstName    string `json:"first_name"`
	LastName     string `json:"last_name"`
	EncodedImage string `json:"facial_image"` // This will hold the Base64 string
}

type VerifyUserPayload struct {
	Email        string `json:"email"`
	EncodedImage string `json:"facial_image"`
}
