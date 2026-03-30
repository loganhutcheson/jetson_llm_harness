#include "publisher.hpp"
#include "subscriber.hpp"

int main() {
    logger temp_logger;
    display temp_display;
    data_sender temp_data_sender;

    publisher temp_publisher;
    temp_publisher.register_sub(&temp_logger);
    temp_publisher.register_sub(&temp_display);
    temp_publisher.notify(24.02f);

    temp_publisher.unregister(&temp_logger);
    temp_publisher.register_sub(&temp_data_sender);
    temp_publisher.notify(44.02f);
    return 0;
}
