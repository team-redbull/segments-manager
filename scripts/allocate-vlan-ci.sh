#!/bin/bash
#
# Segments Manager - Automatic Allocation Script for GitLab CI
#
# This script automatically allocates VLANs to new OpenShift clusters
# in a GitOps repository structure.
#
# Usage:
#   ./allocate-vlan-ci.sh
#
# Environment Variables (Required):
#   - SEGMENTS_MANAGER_URL: URL of the Segments Manager API
#   - SEGMENTS_MANAGER_TIMEOUT: API timeout in seconds
#   - SEGMENTS_MANAGER_RETRIES: Number of retry attempts
#   - CI_PIPELINE_SOURCE: GitLab CI pipeline source
#   - CI_MERGE_REQUEST_TARGET_BRANCH_NAME: Target branch for MR
#

set -e  # Exit on error, but we'll handle errors gracefully

echo "=================================================="
echo "🌐 Segments Manager - Automatic Allocation Pipeline"
echo "=================================================="
echo ""

# ============================================================================
# Configuration
# ============================================================================
SEGMENTS_MANAGER_URL="${SEGMENTS_MANAGER_URL}"
SEGMENTS_MANAGER_TIMEOUT="${SEGMENTS_MANAGER_TIMEOUT}"
SEGMENTS_MANAGER_RETRIES="${SEGMENTS_MANAGER_RETRIES}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Function: Check Segments Manager Health
# ============================================================================
check_segments_manager_health() {
  echo -e "${BLUE}[INFO]${NC} Checking Segments Manager health at ${SEGMENTS_MANAGER_URL}..."

  local http_code
  http_code=$(curl -s -o /dev/null -w "%{http_code}" \
    --connect-timeout "${SEGMENTS_MANAGER_TIMEOUT}" \
    --max-time "${SEGMENTS_MANAGER_TIMEOUT}" \
    "${SEGMENTS_MANAGER_URL}/api/health" 2>/dev/null || echo "000")

  if [ "$http_code" = "200" ]; then
    echo -e "${GREEN}[SUCCESS]${NC} Segments Manager is healthy (HTTP ${http_code})"
    return 0
  else
    echo -e "${YELLOW}[WARNING]${NC} Segments Manager is not available (HTTP ${http_code})"
    return 1
  fi
}

# ============================================================================
# Function: Extract Site from File Path
# ============================================================================
extract_site_from_path() {
  local file_path="$1"

  # Extract site name from path: sites/<site-name>/...
  if [[ "$file_path" =~ sites/([^/]+)/ ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  else
    echo ""
    return 1
  fi
}

# ============================================================================
# Function: Extract Cluster Name from File Path
# ============================================================================
extract_cluster_name() {
  local file_path="$1"

  # Extract filename without extension
  local filename=$(basename "$file_path")
  echo "${filename%.yaml}"
}

# ============================================================================
# Function: Check if Automation is Enabled
# ============================================================================
check_automation_enabled() {
  local file_path="$1"

  # Check if file contains "AutomateVlanAllocation: false"
  if grep -qi "AutomateVlanAllocation:[[:space:]]*false" "$file_path"; then
    return 1  # Automation disabled
  else
    return 0  # Automation enabled (default)
  fi
}

# ============================================================================
# Function: Check if VLAN Already Allocated
# ============================================================================
check_vlan_exists() {
  local file_path="$1"

  # Check if file already contains vlanId field
  if grep -qi "vlanId:[[:space:]]*[0-9]" "$file_path"; then
    return 0  # VLAN exists
  else
    return 1  # VLAN not found
  fi
}

# ============================================================================
# Function: Allocate VLAN from Manager
# ============================================================================
allocate_vlan() {
  local cluster_name="$1"
  local site="$2"

  echo -e "${BLUE}[INFO]${NC} Allocating VLAN for cluster: ${cluster_name} at site: ${site}"

  local response
  local http_code
  local attempt=1

  while [ $attempt -le "$SEGMENTS_MANAGER_RETRIES" ]; do
    echo -e "${BLUE}[INFO]${NC} Attempt ${attempt}/${SEGMENTS_MANAGER_RETRIES}..."

    # Make API call to allocate VLAN
    response=$(curl -s -w "\n%{http_code}" \
      --connect-timeout "${SEGMENTS_MANAGER_TIMEOUT}" \
      --max-time "${SEGMENTS_MANAGER_TIMEOUT}" \
      -X POST "${SEGMENTS_MANAGER_URL}/api/allocate-vlan" \
      -H "Content-Type: application/json" \
      -d "{\"cluster_name\":\"${cluster_name}\",\"site\":\"${site}\"}" \
      2>/dev/null)

    # Extract HTTP code and response body
    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | head -n-1)

    if [ "$http_code" = "200" ]; then
      # Extract VLAN ID from response
      local vlan_id
      vlan_id=$(echo "$response_body" | jq -r '.vlan_id' 2>/dev/null)

      if [ -n "$vlan_id" ] && [ "$vlan_id" != "null" ]; then
        echo -e "${GREEN}[SUCCESS]${NC} Allocated VLAN ID: ${vlan_id}"
        echo "$vlan_id"
        return 0
      else
        echo -e "${RED}[ERROR]${NC} Failed to parse VLAN ID from response"
      fi
    elif [ "$http_code" = "400" ]; then
      # Bad request - might already be allocated
      echo -e "${YELLOW}[WARNING]${NC} Allocation failed (HTTP ${http_code}): ${response_body}"
      echo ""
      return 1
    elif [ "$http_code" = "404" ]; then
      # No available VLANs
      echo -e "${RED}[ERROR]${NC} No available VLANs at site ${site} (HTTP ${http_code})"
      echo ""
      return 1
    else
      echo -e "${YELLOW}[WARNING]${NC} Allocation failed (HTTP ${http_code}), retrying..."
    fi

    attempt=$((attempt + 1))
    sleep 2
  done

  echo -e "${RED}[ERROR]${NC} Failed to allocate VLAN after ${SEGMENTS_MANAGER_RETRIES} attempts"
  echo ""
  return 1
}

# ============================================================================
# Function: Add VLAN ID to Cluster YAML
# ============================================================================
add_vlan_to_yaml() {
  local file_path="$1"
  local vlan_id="$2"

  echo -e "${BLUE}[INFO]${NC} Adding vlanId: ${vlan_id} to ${file_path}..."

  # Check if vlanId already exists
  if grep -qi "vlanId:" "$file_path"; then
    echo -e "${YELLOW}[WARNING]${NC} vlanId field already exists, updating..."
    # Update existing vlanId
    sed -i "s/vlanId:[[:space:]]*[0-9]*/vlanId: ${vlan_id}/I" "$file_path"
  else
    # Add vlanId field at the end of the file
    echo "vlanId: ${vlan_id}" >> "$file_path"
  fi

  echo -e "${GREEN}[SUCCESS]${NC} Updated ${file_path} with vlanId: ${vlan_id}"
}

# ============================================================================
# MAIN LOGIC
# ============================================================================

echo -e "${BLUE}[INFO]${NC} Detecting changed cluster files..."

# Detect changed files in the MR or commit
# For merge requests, compare against target branch
# For commits to main, compare against previous commit
if [ "$CI_PIPELINE_SOURCE" = "merge_request_event" ]; then
  CHANGED_FILES=$(git diff --name-only --diff-filter=A origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}...HEAD)
else
  CHANGED_FILES=$(git diff --name-only --diff-filter=A HEAD~1 HEAD)
fi

# Filter for cluster YAML files in the correct path structure
CLUSTER_FILES=$(echo "$CHANGED_FILES" | grep -E "sites/[^/]+/mce-tenet-clusters/(mce-prod|mce-prep)/[^/]+/[^/]+\.yaml$" || true)

if [ -z "$CLUSTER_FILES" ]; then
  echo -e "${YELLOW}[INFO]${NC} No new cluster files detected. Skipping VLAN allocation."
  exit 0
fi

echo -e "${GREEN}[INFO]${NC} Found $(echo "$CLUSTER_FILES" | wc -l) new cluster file(s)"
echo ""

# Check Segments Manager health first
SEGMENTS_MANAGER_AVAILABLE=false
if check_segments_manager_health; then
  SEGMENTS_MANAGER_AVAILABLE=true
else
  echo -e "${YELLOW}[WARNING]${NC} Segments Manager is not available. Clusters will be created without VLAN allocation."
  echo -e "${YELLOW}[WARNING]${NC} You can manually allocate VLANs later using: POST ${SEGMENTS_MANAGER_URL}/api/allocate-vlan"
  exit 0  # Exit gracefully without failing the pipeline
fi

# Process each cluster file
PROCESSED=0
ALLOCATED=0
SKIPPED=0
FAILED=0

while IFS= read -r file; do
  if [ -z "$file" ]; then
    continue
  fi

  echo ""
  echo "=================================================="
  echo -e "${BLUE}[PROCESSING]${NC} ${file}"
  echo "=================================================="

  # Extract site and cluster name
  SITE=$(extract_site_from_path "$file")
  CLUSTER_NAME=$(extract_cluster_name "$file")

  if [ -z "$SITE" ]; then
    echo -e "${RED}[ERROR]${NC} Could not extract site from path: ${file}"
    FAILED=$((FAILED + 1))
    continue
  fi

  echo -e "${BLUE}[INFO]${NC} Site: ${SITE}"
  echo -e "${BLUE}[INFO]${NC} Cluster: ${CLUSTER_NAME}"

  # Check if automation is enabled
  if ! check_automation_enabled "$file"; then
    echo -e "${YELLOW}[SKIP]${NC} AutomateVlanAllocation is disabled for this cluster"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # Check if VLAN is already allocated
  if check_vlan_exists "$file"; then
    echo -e "${YELLOW}[SKIP]${NC} VLAN already allocated for this cluster"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # Check if Segments Manager is available
  if [ "$SEGMENTS_MANAGER_AVAILABLE" = false ]; then
    echo -e "${YELLOW}[SKIP]${NC} Segments Manager is not available"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # Allocate VLAN for this cluster at its site
  VLAN_ID=$(allocate_vlan "$CLUSTER_NAME" "$SITE")

  if [ -n "$VLAN_ID" ] && [ "$VLAN_ID" != "null" ]; then
    # Add VLAN to YAML
    add_vlan_to_yaml "$file" "$VLAN_ID"
    ALLOCATED=$((ALLOCATED + 1))
  else
    echo -e "${RED}[ERROR]${NC} Failed to allocate VLAN for ${CLUSTER_NAME}"
    FAILED=$((FAILED + 1))
    # Continue processing other clusters instead of failing
  fi

  PROCESSED=$((PROCESSED + 1))
done <<< "$CLUSTER_FILES"

# ============================================================================
# Summary Report
# ============================================================================
echo ""
echo "=================================================="
echo "📊 VLAN Allocation Summary"
echo "=================================================="
echo -e "Total Clusters Processed:  ${PROCESSED}"
echo -e "${GREEN}VLANs Allocated:           ${ALLOCATED}${NC}"
echo -e "${YELLOW}Clusters Skipped:          ${SKIPPED}${NC}"
echo -e "${RED}Allocation Failures:       ${FAILED}${NC}"
echo "=================================================="
echo ""

# Commit changes if any VLANs were allocated
if [ $ALLOCATED -gt 0 ]; then
  echo -e "${BLUE}[INFO]${NC} Committing VLAN allocation changes..."

  git config user.name "Segments Manager Bot"
  git config user.email "segments-manager@automation.local"

  git add .

  # Create commit message
  COMMIT_MSG="chore: Automatic VLAN allocation for ${ALLOCATED} cluster(s) [vlan-bot]"
  git commit -m "${COMMIT_MSG}"

  echo -e "${GREEN}[SUCCESS]${NC} Changes committed"
else
  echo -e "${YELLOW}[INFO]${NC} No changes to commit"
fi

# Exit successfully even if some allocations failed
# This ensures cluster creation can proceed
echo -e "${GREEN}[COMPLETE]${NC} VLAN allocation phase completed"
exit 0
