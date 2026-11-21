package lab.springsandbox;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** Entry point of the sandbox service. */
@SpringBootApplication
public class SpringSandboxApplication {

    /** Starts the service. */
    public static void main(String[] args) {
        SpringApplication.run(SpringSandboxApplication.class, args);
    }
}
