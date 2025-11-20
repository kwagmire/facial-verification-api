package handlers

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"strconv"

	"github.com/kwagmire/facial-verification-api/db"
	"github.com/kwagmire/facial-verification-api/models"
)

type verifyFacePayload struct {
	RegImg string `json:"regimg"`
	VerImg string `json:"verimg"`
}

type verificationResponse struct {
	IsMatch   bool    `json:"is_match"`
	Distance  float64 `json:"distance"`
	Threshold float64 `json:"threshold"`
	Time      float64 `json:"time"`
}

func VerifyUser(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		respondWithError(w, "Unaccepted method", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		respondWithError(w, "Error reading request body", http.StatusBadRequest)
		return
	}

	var thisRequest models.VerifyUserPayload
	err = json.Unmarshal(body, &thisRequest)
	if err != nil {
		respondWithError(w, "Invalid request payload", http.StatusBadRequest)
		return
	}

	if thisRequest.Email == "" || thisRequest.EncodedImage == "" {
		respondWithError(w, "All fields are required", http.StatusBadRequest)
		return
	}

	query := `
		SELECT
			id,
			regimage_url
		FROM users
		WHERE email = $1`
	var userID int
	var baseImageURL string
	err = db.DB.QueryRow(query, thisRequest.Email).Scan(
		&userID,
		&baseImageURL,
	)
	if err == sql.ErrNoRows {
		respondWithError(w, "User account doesn't exist", http.StatusUnauthorized)
		return
	}
	if err != nil {
		respondWithError(w, "Database error: "+err.Error(), http.StatusInternalServerError)
		return
	}

	/*1. Decode the Base64 string into bytes.
	decodedData, err := base64.StdEncoding.DecodeString(thisRequest.EncodedImage)
	if err != nil {
		respondWithError(w, "Invalid Base64 string", http.StatusBadRequest)
		return
	}

	// 2. Detect the content type (image format) from the decoded bytes.
	fileType := http.DetectContentType(decodedData)
	if fileType != "image/jpeg" {
		respondWithError(w, "Unsupported image format", http.StatusBadRequest)
		return
	}*/

	const microserviceURL = "http://localhost:8001/verify"
	// 2. Create the JSON payload
	payload := verifyFacePayload{
		RegImg: baseImageURL,
		VerImg: thisRequest.EncodedImage,
	}

	// Marshal the payload struct into JSON bytes
	jsonPayload, err := json.Marshal(payload)
	if err != nil {
		respondWithError(w, "error marshalling json: "+err.Error(), http.StatusInternalServerError)
		return
	}

	// 3. Create and send the HTTP request
	req, err := http.NewRequest("POST", microserviceURL, bytes.NewBuffer(jsonPayload))
	if err != nil {
		respondWithError(w, "error creating request: "+err.Error(), http.StatusInternalServerError)
		return
	}

	// Set the Content-Type header to application/json
	req.Header.Set("Content-Type", "application/json")

	// Send the request
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		respondWithError(w, "error sending request to python service: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer resp.Body.Close()

	// 4. Handle the response
	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		respondWithError(w, "python service returned error (status "+strconv.Itoa(resp.StatusCode)+"): "+string(bodyBytes), http.StatusInternalServerError)
		return
	}

	// Decode the successful JSON response
	var verificationResp verificationResponse
	if err = json.NewDecoder(resp.Body).Decode(&verificationResp); err != nil {
		respondWithError(w, "error decoding json response: "+err.Error(), http.StatusInternalServerError)
	}

	respondWithJSON(w, http.StatusOK, verificationResp)
}
