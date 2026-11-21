# spring-sandbox

The Sandbox is a small Spring Boot service kept correct on purpose, with a check that reports each Stage and the Pass rate. It is a fixture for measuring verification on the JVM stack, in the same Summary format the other stacks' sandboxes use. Terms such as Stage, Summary and Planted defect mean what the [glossary](GLOSSARY.md) says.

The service has one endpoint and one domain class. `GET /pass-rate?passed=3&total=4` returns `{"passed":3,"total":4,"percent":75}`, and a pair that is not a valid Pass rate (`passed=5&total=4`, `total=0`) gets a 400.

## Prerequisites

- A JDK, version 17 or newer, on `PATH` or in `JAVA_HOME`. Nothing else is installed by hand.
- Network on the first run. The Gradle wrapper downloads Gradle 9.9.2 and checks its sha256 (`gradle/wrapper/gradle-wrapper.properties`), then Gradle downloads the libraries and plugins named in `gradle.lockfile` and `buildscript-gradle.lockfile` from Maven Central.

## Check

```bash
./check
```

It runs four Stages in order and prints a table and `passed N of 4`:

| Stage | Command |
|---|---|
| `compile` | `./gradlew classes testClasses archunitClasses` |
| `checkstyle` | `./gradlew checkstyleMain checkstyleTest checkstyleArchunit` |
| `test` | `./gradlew test --rerun` |
| `archunit` | `./gradlew archunit --rerun` |

Every Stage runs even after an earlier one failed, so the Pass rate counts all four. The exception is that `test` and `archunit` are `not-run` when `compile` did not pass, because both need compiled classes. The exit code is 0 only when all four passed.

```bash
./check --json
```

prints the Summary, one JSON object on one line of stdout, and sends all build output to stderr:

```json
{"project": "spring-sandbox", "stack": "spring", "stages": [{"name": "compile", "status": "pass", "duration_ms": 513, "command": "./gradlew classes testClasses archunitClasses"}, {"name": "checkstyle", "status": "pass", "duration_ms": 457, "command": "./gradlew checkstyleMain checkstyleTest checkstyleArchunit"}, {"name": "test", "status": "pass", "duration_ms": 1976, "command": "./gradlew test --rerun"}, {"name": "archunit", "status": "pass", "duration_ms": 1407, "command": "./gradlew archunit --rerun"}], "passed": 4, "total": 4}
```

## The verify-spring skill

`.claude/skills/verify-spring/SKILL.md` is a Claude Code skill scoped to this Project. Start Claude Code in this folder and type:

```
/verify-spring
```

Claude runs `./check --json` once, reports each Stage's status and the Pass rate, and stops. The skill edits nothing, reads no secrets and calls no model or service. A session started at the repo root can load the skill once Claude has worked on a file in this folder.

## Planted defects

```bash
./planted-defects
```

For each Stage it copies the Project to a temporary folder, adds one Planted defect there (a type error, an unused import, a failing JUnit test, a domain class that uses the web package), runs `./check --json` in the copy and compares the result with what that defect should cause. It prints one table row per case and exits 0 only when every row says `ok`. Nothing is written to this folder.

## Run the service

```bash
./gradlew bootRun
curl 'http://127.0.0.1:8080/pass-rate?passed=3&total=4'
```

It listens on loopback only (`src/main/resources/application.properties`).

## Dependencies

Locking is strict: a library or plugin that is not in a lockfile fails the build, and so does a missing lockfile. After changing a version in `build.gradle`, rewrite both lockfiles and commit them with the change:

```bash
./gradlew dependencies --write-locks
```

Choices worth knowing before changing the build:

- **Gradle comes from the wrapper**, not from whatever `gradle` the machine has. The wrapper pins the version and the distribution's sha256, so the build tool is locked like the libraries are. The cost is one committed binary, `gradle/wrapper/gradle-wrapper.jar`. Its sha256 is `621008afc4f5d59357fcf06ffa644dd5aade5e091bdc363742710445f73cdaf8`, the value Gradle publishes for 9.9.2 at <https://gradle.org/release-checksums/>.
- **The code compiles to Java 17 with no toolchain block**, so Gradle never downloads a JDK and any JDK from 17 up works.
- **Checkstyle is pinned to 12.3.1**, the newest release that runs on JDK 17. Releases from 13.0.0 need JDK 21.
- **`config/checkstyle/checkstyle.xml` is a trimmed rule set**, with every rule at error severity. The stock Google and Sun configurations report far more than a sandbox needs.
- **Maven Central is the only registry**, for plugins as well as libraries (`settings.gradle`).
