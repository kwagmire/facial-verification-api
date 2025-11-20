package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"strconv"

	"github.com/kwagmire/facial-verification-api/db"
	"github.com/kwagmire/facial-verification-api/models"

	"github.com/cloudinary/cloudinary-go/v2"
	"github.com/cloudinary/cloudinary-go/v2/api/uploader"
	"github.com/lib/pq"
)

// This struct matches the JSON payload for the microservice detect-face endpoint
type detectFacePayload struct {
	Img string `json:"img"`
}

// This struct matches the JSON response from our Python API
type detectionResponse struct {
	Status     string  `json:"status"`
	IsReal     bool    `json:"is_real"`
	AntiSScore float64 `json:"antispoof_score"`
}

func RegisterUser(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		respondWithError(w, "Unaccepted method", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		respondWithError(w, "Error reading request body", http.StatusBadRequest)
		return
	}

	var thisRequest models.RegisterUserPayload
	err = json.Unmarshal(body, &thisRequest)
	if err != nil {
		respondWithError(w, "Invalid request payload", http.StatusBadRequest)
		return
	}

	if thisRequest.Email == "" ||
		thisRequest.FirstName == "" ||
		thisRequest.LastName == "" ||
		thisRequest.EncodedImage == "" {
		respondWithError(w, "All fields are required", http.StatusBadRequest)
		return
	}

	/*/ 1. Decode the Base64 string into bytes.
	decodedData, err := base64.StdEncoding.DecodeString(thisRequest.EncodedImage)
	if err != nil {
		respondWithError(w, "Invalid Base64 string: "+err.Error(), http.StatusBadRequest)
		return
	}


	// 2. Detect the content type (image format) from the decoded bytes.
	fileType := http.DetectContentType(decodedData)
	if fileType != "image/jpeg" {
		respondWithError(w, "Unsupported image format", http.StatusBadRequest)
		return
	}
	*/

	const microserviceURL = "http://localhost:8001/detect-face"
	// 2. Create the JSON payload
	payload := detectFacePayload{
		Img: thisRequest.EncodedImage,
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

	/* Decode the successful JSON response
		var verificationResp detectionResponse
		if err = json.NewDecoder(resp.Body).Decode(&verificationResp); err != nil {
			respondWithError(w, "error decoding json response: "+err.Error(), http.StatusInternalServerError)
			return
		}

		return &verificationResp, nil
	}
		_, err = core.CheckFace(baseFilepath)
		if err != nil {
			log.Printf("Failed to recognize file: %v", err)
			respondWithError(w, "Failed to find a face", http.StatusUnprocessableEntity)
			return
		}*/

	ctx := context.Background()

	cld, err := cloudinary.New()
	if err != nil {
		log.Printf("Failed to create Cloudinary instance: %v", err)
		respondWithError(w, "Error creating Cloudinary instance", http.StatusInternalServerError)
		return
	}

	uploadResult, err := cld.Upload.Upload(ctx, thisRequest.EncodedImage, uploader.UploadParams{})
	if err != nil {
		log.Printf("Failed to upload file: %v", err)
		respondWithError(w, "Error uploading image to Cloudinary", http.StatusInternalServerError)
		return
	}

	query := `
		INSERT INTO users (
			email,
			first_name,
			last_name,
			regimage_url
		) VALUES ($1, $2, $3, $4
		) RETURNING id`
	var userID int
	err = db.DB.QueryRow(
		query,
		thisRequest.Email,
		thisRequest.FirstName,
		thisRequest.LastName,
		uploadResult.SecureURL,
	).Scan(&userID)
	if err != nil {
		if dbError, ok := err.(*pq.Error); ok && dbError.Code.Name() == "unique_violation" {
			respondWithError(w, "Email already exists", http.StatusConflict)
			return
		}
		respondWithError(w, "Failed to register user: "+err.Error(), http.StatusInternalServerError)
		return
	}

	respondWithJSON(w, http.StatusCreated, map[string]string{"message": "Registration successful!"})
}
