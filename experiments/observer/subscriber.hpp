#pragma once
#include <cstdio>

class subscriber {
  public:
    virtual void update(float) = 0;
    virtual ~subscriber() = default;
};

class display : public subscriber {
  public:
    void update(float temp) override { printf("Displaying temperature %.2f \r\n", temp); }
};

class data_sender : public subscriber {
  public:
    void update(float temp) override { printf("Sending temperature %.2f \r\n", temp); }
};

class logger : public subscriber {
  public:
    void update(float temp) override { printf("Logging temperature %.2f \r\n", temp); }
};
