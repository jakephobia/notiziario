/**
 * Sveglia il workflow del Notiziario da Google Apps Script.
 *
 * Setup:
 * 1. script.google.com -> Nuovo progetto.
 * 2. Incolla questo file.
 * 3. Impostazioni progetto -> Fuso orario: Europe/Rome.
 * 4. Impostazioni progetto -> Proprietà script -> aggiungi GITHUB_TOKEN
 *    con una fine-grained PAT limitata al repo e Actions: read/write.
 * 5. Trigger -> Aggiungi trigger -> triggerNotiziario -> A tempo ->
 *    Timer a minuti -> ogni 5 minuti.
 * 6. Autorizza al primo avvio. Lo script lavora solo tra le 7 e le 8
 *    (Europe/Rome) e salta se l'episodio di oggi esiste già.
 */

const REPO = "jakephobia/notiziario";
const WORKFLOW = "notiziario.yml";
const DURATA = "standard";

function triggerNotiziario() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty("GITHUB_TOKEN");
  if (!token) {
    throw new Error("Manca GITHUB_TOKEN nelle Proprietà script.");
  }

  const adesso = new Date();
  const ora = Number(Utilities.formatDate(adesso, "Europe/Rome", "H"));
  if (ora < 7 || ora > 8) {
    return;
  }

  const oggi = Utilities.formatDate(adesso, "Europe/Rome", "yyyy-MM-dd");
  if (props.getProperty("ULTIMO_GIORNO") === oggi) {
    return;
  }

  const storicoUrl =
    "https://raw.githubusercontent.com/" + REPO + "/main/docs/storico.json";
  const storicoResponse = UrlFetchApp.fetch(storicoUrl, {
    muteHttpExceptions: true,
  });
  if (storicoResponse.getResponseCode() === 200) {
    const storico = JSON.parse(storicoResponse.getContentText() || "{}");
    const episodi = Array.isArray(storico.episodi) ? storico.episodi : [];
    if (episodi.some((episodio) => String(episodio.data) === oggi)) {
      props.setProperty("ULTIMO_GIORNO", oggi);
      Logger.log("Episodio di oggi già presente: salto.");
      return;
    }
  }

  const url =
    "https://api.github.com/repos/" +
    REPO +
    "/actions/workflows/" +
    WORKFLOW +
    "/dispatches";
  const risposta = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    headers: {
      Authorization: "Bearer " + token,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    payload: JSON.stringify({
      ref: "main",
      inputs: { durata: DURATA },
    }),
    muteHttpExceptions: true,
  });

  const codice = risposta.getResponseCode();
  if (codice !== 204) {
    throw new Error(
      "GitHub HTTP " + codice + ": " + risposta.getContentText()
    );
  }
  props.setProperty("ULTIMO_GIORNO", oggi);
  Logger.log("Workflow avviato per " + oggi + ".");
}

function testToken() {
  const token = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
  if (!token) {
    throw new Error("Manca GITHUB_TOKEN nelle Proprietà script.");
  }
  const risposta = UrlFetchApp.fetch(
    "https://api.github.com/repos/" + REPO + "/actions/workflows",
    {
      headers: {
        Authorization: "Bearer " + token,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      muteHttpExceptions: true,
    }
  );
  Logger.log("HTTP " + risposta.getResponseCode());
}
