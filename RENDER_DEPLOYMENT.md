# Deploy the Release Risk Analyzer to Render (free web service)

This hosted configuration uses the GitHub REST API rather than launching the
GitHub MCP Docker container. Standard Render web services do not provide a
Docker daemon for this nested-container setup. The original MCP implementation
is preserved in `ml/github_service_mcp.py` for local demonstrations.

## 1. Prepare GitHub safely

1. Rotate any GitHub or Groq credential that was included in a shared ZIP or
   committed to Git history.
2. Keep real credentials only in your local `ml/.env` and Render's Environment
   settings. Never commit `.env`.
3. The GitHub token should have read access to the target repository's pull
   requests, issues, contents/metadata, and Actions workflow runs. For a fine-
   grained PAT, grant read-only access to the relevant repository permissions.

## 2. Push the updated project to GitHub

Commit and push the updated project files to the branch you want Render to
build. Do not upload `.env`, `.venv`, `.git`, `__pycache__`, or generated Excel
files. The `.gitignore` in this project excludes these.

## 3. Create the Render service

The repository includes `render.yaml`. In Render, choose **New + → Blueprint**
and connect the repository. Review the service settings before applying:

- Root directory: `ml`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn api:app --host 0.0.0.0 --port $PORT`
- Plan: Free

If you create a Web Service manually instead, use those same settings.

## 4. Add environment variables

In the Render service's **Environment** tab, set:

- `GROQ_API_KEY`: your rotated Groq key
- `GROQ_MODEL`: `llama-3.3-70b-versatile` (or a model currently enabled for your Groq account)
- `GITHUB_PERSONAL_ACCESS_TOKEN`: your rotated GitHub token

Do not add quotation marks around the values. Save changes and redeploy.

## 5. Test the deployment

1. Open `https://YOUR-SERVICE.onrender.com/health`. It should return `status: ok`.
2. Open the service root URL. The analyzer page should load.
3. Enter a repository owner, repository name, and pull request number; click
   **Fetch release metrics from GitHub**.
4. Review the populated values, then click **Assess risk and generate Excel**.
5. Download the generated workbook.

## Important behaviour and limitations

- Free Render services can spin down after inactivity; the first request after
  sleeping can take around a minute to wake.
- The GitHub integration reads up to 1,000 records per paginated list (files,
  open issues, and completed workflow runs) to bound request volume. The
  `recent_failures` count is therefore the failures found in that retrieved
  window, not necessarily the repository's all-time failure count.
- `affected_modules` is estimated from directory names in changed file paths.
  Review it because repository folder structure is not always the same as
  business/module boundaries.
- `criticality` is read from PR labels named `criticality:high|medium|low` or
  `priority:high|medium|low`; if none exists, it defaults to `medium`.
- Excel reports are kept in application memory. They are intended for an
  immediate download and can disappear when the service restarts or sleeps.
- This is an academic demonstration, not a production release-control system.
  Anyone who can access the public URL can submit requests and consume your
  Groq quota. Do not expose sensitive repository or production information.
  Add authentication and rate limiting before broader use.
